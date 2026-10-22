"""MEV Service - Production-ready service for MEV operations.

This module provides a high-level async service for interacting with
the SCBA MEV (Mesa de Entradas Virtual) system.

Key Design Decisions:
1. Each method performs full authentication cycle (login -> POS login -> action)
   This ensures stateless operation suitable for serverless/API environments.

2. Credentials are passed with each request to support multi-tenant scenarios
   where different users may be making requests.

3. Async-first design for FastAPI integration.

4. Clean separation between HTTP operations and business logic.

Usage:
    async with MEVService() as service:
        files = await service.search_files(request)
"""

import asyncio
import logging
from typing import Optional

from .http_client import MEVHttpClient, HttpClientConfig
from .parsers import (
    LoginPageParser,
    SearchResultPageParser,
    FileOrdersPageParser,
    OrderPageParser,
    SetIdParser,
    JuzgadosDropdownParser,
)
from .models import (
    Credentials,
    SearchFilesRequest,
    SearchFamiliaRequest,
    CourtFileRequest,
    FileOrderRequest,
    CourtFile,
    FullCourtFile,
    FileOrder,
    SearchOption,
    RadioOption,
    FueroType,
    CausaContext,
    OrderWithText,
)
from .exceptions import (
    AuthenticationError,
    SearchError,
    ParseError,
    NotFoundError,
    MEVError,
)


logger = logging.getLogger(__name__)


class MEVService:
    """
    Production-ready async service for MEV operations.

    This service follows a stateless pattern where each operation:
    1. Authenticates with provided credentials
    2. Sets the district context via POSLoguin
    3. Performs the requested action
    4. Returns the result

    This design is ideal for:
    - FastAPI/async web frameworks
    - Serverless deployments (AWS Lambda, etc.)
    - Multi-tenant applications
    - Load-balanced environments

    Usage:
        # As context manager (recommended)
        async with MEVService() as service:
            files = await service.search_files(request)

        # Manual lifecycle
        service = MEVService()
        try:
            files = await service.search_files(request)
        finally:
            await service.close()
    """

    # MEV endpoints
    LOGIN_PATH = "/loguin.asp"
    POST_LOGIN_PATH = "/POSLoguin.asp"
    SEARCH_PATH = "/busqueda.asp"
    RESULTS_PATH = "/resultados.asp"
    MUESTRA_CAUSAS_PATH = "/MuestraCausas.asp"
    PROCESALES_PATH = "/procesales.asp"
    PROVEIDO_PATH = "/proveido.asp"

    def __init__(
        self,
        config: Optional[HttpClientConfig] = None,
        debug: bool = False,
    ):
        """
        Initialize the MEV service.

        Args:
            config: HTTP client configuration (optional)
            debug: Enable debug logging
        """
        self._config = config or HttpClientConfig()
        self._debug = debug
        self._client: Optional[MEVHttpClient] = None

        # Initialize parsers (stateless, can be reused)
        self._login_parser = LoginPageParser()
        self._search_parser = SearchResultPageParser()
        self._file_orders_parser = FileOrdersPageParser()
        self._order_parser = OrderPageParser()
        self._set_id_parser = SetIdParser()
        self._juzgados_parser = JuzgadosDropdownParser()

    async def __aenter__(self) -> "MEVService":
        """Async context manager entry."""
        self._client = MEVHttpClient(self._config)
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def close(self) -> None:
        """Close the service and release resources."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    # =========================================================================
    # AUTHENTICATION (internal)
    # =========================================================================

    async def _ensure_client(self) -> None:
        """Ensure HTTP client is initialized."""
        if self._client is None:
            self._client = MEVHttpClient(self._config)
            await self._client.__aenter__()

    async def _authenticate(self, credentials: Credentials) -> None:
        """
        Perform authentication with MEV.

        Args:
            credentials: User credentials

        Raises:
            AuthenticationError: If authentication fails
        """
        await self._ensure_client()

        # Clear any existing session
        self._client.clear_session()

        # Step 1: Get initial cookie
        try:
            await self._client.fetch_initial_cookie()
        except Exception as e:
            raise AuthenticationError(
                "Failed to obtain initial session cookie",
                {"error": str(e)},
            )

        # Step 2: Login
        login_data = {
            "usuario": credentials.username,
            "clave": credentials.password,
            "DeptoRegistrado": "aa",  # Initial district code
        }

        try:
            response = await self._client.post(
                f"{self.LOGIN_PATH}?familiadepto=",
                data=login_data,
                referer=self.LOGIN_PATH,
            )
        except Exception as e:
            raise AuthenticationError(
                "Login request failed",
                {"error": str(e)},
            )

        # Verify login success
        user = self._login_parser.parse(response.text)
        if user is None:
            error_msg = self._login_parser.extract_error_message(response.text)
            raise AuthenticationError(
                error_msg or "Authentication failed - invalid credentials or session expired",
                {"username": credentials.username},
            )

        # Verify returned username contains the submitted username
        if credentials.username.lower() not in user.username.lower():
            raise AuthenticationError(
                "Authentication failed - returned user does not match submitted credentials",
                {"expected": credentials.username, "got": user.username},
            )

        if self._debug:
            logger.debug(f"Authenticated as: {user.username} ({user.fullname})")

    async def _set_district_context(
        self,
        district_code: str,
        fuero_type: FueroType = FueroType.CIVIL_COMERCIAL,
    ) -> str:
        """
        Set the district context via POSLoguin.

        Args:
            district_code: District tracking code (e.g., "80")
            fuero_type: Fuero type (CIVIL_COMERCIAL or FAMILIA)

        Returns:
            HTML content of the POSLoguin response (useful for Familia set parsing)

        Raises:
            MEVError: If setting district context fails
        """
        district_data = {
            "TipoDto": "CC",
            "DtoJudElegido": district_code,
            "Aceptar": "Aceptar",
        }

        # Add TipoF parameter for Fuero de Familia
        if fuero_type == FueroType.FAMILIA:
            district_data["TipoF"] = fuero_type.value

        try:
            response = await self._client.post(
                self.POST_LOGIN_PATH,
                data=district_data,
                referer=self.POST_LOGIN_PATH,
            )
        except Exception as e:
            raise MEVError(
                "Failed to set district context",
                {"district_code": district_code, "error": str(e)},
            )

        if self._debug:
            logger.debug(f"District context set to: {district_code} (fuero: {fuero_type.name})")

        return response.text

    async def _prepare_session(
        self,
        credentials: Credentials,
        district_code: str,
        fuero_type: FueroType = FueroType.CIVIL_COMERCIAL,
    ) -> str:
        """
        Complete preparation for an operation: authenticate and set district.

        Args:
            credentials: User credentials
            district_code: District tracking code
            fuero_type: Fuero type (CIVIL_COMERCIAL or FAMILIA)

        Returns:
            HTML content from POSLoguin response
        """
        await self._authenticate(credentials)
        return await self._set_district_context(district_code, fuero_type)

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    async def search_files(self, request: SearchFilesRequest) -> list[CourtFile]:
        """
        Search for court files.

        Performs: Login -> Set District -> Search -> Parse Results

        Args:
            request: Search parameters including credentials

        Returns:
            List of CourtFile objects matching the search criteria

        Raises:
            AuthenticationError: If authentication fails
            SearchError: If search fails
            ParseError: If parsing results fails

        Example:
            files = await service.search_files(SearchFilesRequest(
                credentials=Credentials(username="user", password="pass"),
                district_code="80",
                court_id="GAM2078",
                case_number="14107"
            ))
        """
        await self._prepare_session(request.credentials, request.district_code)

        # Perform search
        search_form = request.to_form_data()

        if self._debug:
            logger.debug(f"Search form data: {search_form}")

        try:
            response = await self._client.post(
                self.SEARCH_PATH,
                data=search_form,
                referer="/busqueda.asp",
            )
        except Exception as e:
            raise SearchError(
                "Search request failed",
                {"court_id": request.court_id, "error": str(e)},
            )

        # Parse results (page 1)
        try:
            files = self._search_parser.parse(response.text)
        except Exception as e:
            raise ParseError(
                "Failed to parse search results",
                {"error": str(e)},
            )

        # Paginate: fetch remaining pages if any
        last_page = self._search_parser.get_last_page(response.text)

        if self._debug:
            total = self._search_parser.get_total_count(response.text)
            logger.debug(f"Found {len(files)} files on page 1 (total: {total}, last_page: {last_page})")

        if last_page > 1:
            radio_value = search_form["radio"]
            for page in range(2, last_page + 1):
                try:
                    page_response = await self._client.get(
                        self.MUESTRA_CAUSAS_PATH,
                        params={
                            "radio": radio_value,
                            "pagina": str(page),
                            "pOrden": "xCa",
                            "pOrdenAD": "Asc",
                            "NroColumna": "0",
                        },
                    )
                    page_files = self._search_parser.parse(page_response.text)
                    files.extend(page_files)

                    if self._debug:
                        logger.debug(f"Page {page}: found {len(page_files)} files")
                except Exception as e:
                    logger.warning(f"Failed to fetch search results page {page}: {e}")
                    break

            # Deduplicate by (id, court_id) preserving order
            seen: set[tuple[str, str]] = set()
            unique_files: list[CourtFile] = []
            for f in files:
                key = (f.id, f.court_id)
                if key not in seen:
                    seen.add(key)
                    unique_files.append(f)
            files = unique_files

        return files

    async def search_familia_files(
        self, request: SearchFamiliaRequest
    ) -> list[CourtFile]:
        """
        Search for court files in Fuero de Familia.

        Unlike Civil/Comercial searches, Familia uses a set-based approach:
        1. Login and set district with FueroType.FAMILIA
        2. Parse the authorized set ID from POSLoguin response
        3. Search by set to get juzgados list
        4. Iterate all juzgados to aggregate causas

        Args:
            request: Search parameters (credentials + district_code only)

        Returns:
            List of CourtFile objects from all juzgados in the district,
            each with court_id and court_name populated.

        Raises:
            AuthenticationError: If authentication fails
            SearchError: If user has no familia access or search fails
            ParseError: If parsing results fails

        Example:
            files = await service.search_familia_files(SearchFamiliaRequest(
                credentials=Credentials(username="user", password="pass"),
                district_code="80"
            ))
        """
        # Step 1: Authenticate and set district with Familia fuero
        pos_login_html = await self._prepare_session(
            request.credentials,
            request.district_code,
            FueroType.FAMILIA,
        )

        # Step 2: Parse set ID from POSLoguin response
        set_id = self._set_id_parser.parse(pos_login_html)
        if not set_id:
            raise SearchError(
                "El usuario no tiene causas autorizadas en este Departamento Judicial.",
                {"district_code": request.district_code},
            )

        if self._debug:
            logger.debug(f"Found Familia set ID: {set_id}")

        # Step 3: POST to Busqueda.asp with set-based search params
        from datetime import datetime, timedelta

        now = datetime.now()
        from_date = now - timedelta(days=2)

        def format_date(dt: datetime) -> str:
            return f"{dt.month}/{dt.day}/{dt.year}"

        search_form = {
            "OpcionBusqueda": "3",  # Search by set
            "busca": set_id,
            "radio": "xSb",  # Radio option for set-based search
            "caratula": "xxx",
            "NCausa": "0",
            "NInterno": "0",
            "Set": set_id,
            "Desde": format_date(from_date),
            "Hasta": format_date(now),
            "SetNovedades": "",
            "TipoCausa": "Am",
            "Buscar": "Buscar",
        }

        try:
            await self._client.post(
                self.SEARCH_PATH,
                data=search_form,
                referer="/busqueda.asp",
            )
        except Exception as e:
            raise SearchError(
                "No pudo hallarse un set de causas para buscar en este Departamento Judicial.",
                {"set_id": set_id, "error": str(e)},
            )

        # Step 4: GET results page to get juzgados dropdown
        try:
            results_response = await self._client.get(
                self.RESULTS_PATH,
                params={
                    "nidset": set_id,
                    "sfechadesde": "",
                    "sfechahasta": "",
                    "pOrden": "xCa",
                    "pOrdenAD": "Asc",
                },
            )
        except Exception as e:
            raise SearchError(
                "Un error ha ocurrido.",
                {"set_id": set_id, "error": str(e)},
            )

        # Step 5: Parse juzgados from dropdown
        juzgados = self._juzgados_parser.parse(results_response.text)
        if not juzgados:
            if self._debug:
                logger.debug("No juzgados found in dropdown")
            return []

        if self._debug:
            logger.debug(f"Found {len(juzgados)} juzgados to query")

        # Step 6: Iterate each juzgado to get causas
        all_files: list[CourtFile] = []

        for juzgado in juzgados:
            try:
                juzgado_form = {
                    "JuzgadoElegido": juzgado.id,
                    "Consultar": "Consultar",
                    "snrointerno": "",
                    "scaratula": "",
                    "menu1": "resultados.asp?pagina=1&pOrden=xCa&pOrdenAD=Asc&pNroColumna=1",
                }

                response = await self._client.post(
                    f"{self.RESULTS_PATH}?sFechaDesde=&sFechaHasta=",
                    data=juzgado_form,
                    referer=self.RESULTS_PATH,
                )

                # Parse causas for this juzgado (page 1)
                files = self._search_parser.parse(response.text)

                # Paginate remaining pages for this juzgado
                last_page = self._search_parser.get_last_page(response.text)
                if last_page > 1:
                    for page in range(2, last_page + 1):
                        try:
                            page_response = await self._client.get(
                                self.MUESTRA_CAUSAS_PATH,
                                params={
                                    "radio": "xCa",
                                    "pagina": str(page),
                                    "pOrden": "xCa",
                                    "pOrdenAD": "Asc",
                                    "NroColumna": "0",
                                },
                            )
                            page_files = self._search_parser.parse(page_response.text)
                            files.extend(page_files)
                        except Exception:
                            break

                # Set court_name for each file
                for file in files:
                    file.court_name = juzgado.name

                all_files.extend(files)

                if self._debug:
                    logger.debug(
                        f"Juzgado {juzgado.name}: found {len(files)} files (pages: {last_page})"
                    )

            except Exception as e:
                if self._debug:
                    logger.warning(
                        f"Failed to get files for juzgado {juzgado.id}: {e}"
                    )
                # Continue with other juzgados even if one fails
                continue

        # Deduplicate by (id, court_id) preserving order
        seen: set[tuple[str, str]] = set()
        unique_files: list[CourtFile] = []
        for f in all_files:
            key = (f.id, f.court_id)
            if key not in seen:
                seen.add(key)
                unique_files.append(f)

        if self._debug:
            logger.debug(f"Total files found across all juzgados: {len(unique_files)} (before dedup: {len(all_files)})")

        return unique_files

    async def get_file(self, request: CourtFileRequest) -> CourtFile:
        """
        Get a specific court file by ID.

        Performs: Login -> Set District -> Fetch File -> Parse

        Args:
            request: File request with credentials and identifiers

        Returns:
            CourtFile with file details

        Raises:
            AuthenticationError: If authentication fails
            NotFoundError: If file is not found
            ParseError: If parsing fails

        Example:
            file = await service.get_file(CourtFileRequest(
                credentials=Credentials(username="user", password="pass"),
                district_code="80",
                court_id="GAM2078",
                case_id="1281688"
            ))
        """
        await self._prepare_session(request.credentials, request.district_code)

        # Fetch file page - use correct path based on fuero
        params = {
            "nidCausa": request.case_id,
            "pidJuzgado": request.court_id,
        }

        procesales_path = self.PROCESALES_PATH

        try:
            response = await self._client.get(
                procesales_path,
                params=params,
            )
        except Exception as e:
            raise MEVError(
                "Failed to fetch file",
                {"case_id": request.case_id, "error": str(e)},
            )

        # Parse file info and orders
        try:
            file_info, orders = self._file_orders_parser.parse_with_file_info(
                response.text, request.case_id, request.court_id
            )
        except Exception as e:
            raise ParseError(
                "Failed to parse file details",
                {"error": str(e)},
            )

        if file_info is None:
            raise NotFoundError(
                "File not found or access denied",
                {"case_id": request.case_id, "court_id": request.court_id},
            )

        # Update file with latest order info if available
        if orders:
            latest = max(orders, key=lambda o: o.date)
            file_info.last_update = latest.date
            file_info.last_order_title = latest.title

        return file_info

    async def download_file(self, request: CourtFileRequest) -> FullCourtFile:
        """
        Download a court file with all its orders.

        Performs: Login -> Set District -> Fetch File -> Parse All Orders

        Args:
            request: File request with credentials and identifiers

        Returns:
            FullCourtFile with file details and all order summaries

        Raises:
            AuthenticationError: If authentication fails
            NotFoundError: If file is not found
            ParseError: If parsing fails

        Example:
            full_file = await service.download_file(CourtFileRequest(
                credentials=Credentials(username="user", password="pass"),
                district_code="80",
                court_id="GAM2078",
                case_id="1281688"
            ))
            print(f"File has {full_file.order_count} orders")
        """
        await self._prepare_session(request.credentials, request.district_code)

        # Fetch file page - use correct path based on fuero
        params = {
            "nidCausa": request.case_id,
            "pidJuzgado": request.court_id,
        }        
        procesales_path = self.PROCESALES_PATH

        try:
            response = await self._client.get(
                procesales_path,
                params=params,
            )
        except Exception as e:
            raise MEVError(
                "Failed to fetch file",
                {"case_id": request.case_id, "error": str(e)},
            )

        # Parse file info, orders, court name, and district name
        try:
            full_file = self._file_orders_parser.parse_full_file(
                response.text, request.case_id, request.court_id
            )
        except Exception as e:
            raise ParseError(
                "Failed to parse file and orders",
                {"error": str(e)},
            )

        if full_file.file is None:
            # Create minimal file info
            full_file = FullCourtFile(
                file=CourtFile(
                    id=request.case_id,
                    court_id=request.court_id,
                    case_caption="",
                    status="",
                    reception_number="",
                    file_number="",
                ),
                orders=full_file.orders,
                court_name=full_file.court_name,
                district_name=full_file.district_name,
            )

        # Update file with latest order info
        if full_file.orders:
            latest = max(full_file.orders, key=lambda o: o.date)
            full_file.file.last_update = latest.date
            full_file.file.last_order_title = latest.title

        return full_file

    async def read_order(self, request: FileOrderRequest) -> FileOrder:
        """
        Read the full text of a court order.

        Performs: Login -> Set District -> Fetch Order -> Parse Text

        Args:
            request: Order request with credentials and identifiers

        Returns:
            FileOrder with full order text

        Raises:
            AuthenticationError: If authentication fails
            NotFoundError: If order is not found
            ParseError: If parsing fails

        Example:
            order = await service.read_order(FileOrderRequest(
                credentials=Credentials(username="user", password="pass"),
                district_code="80",
                court_id="GAM2078",
                order_code="1933063",
                position="27606093",
                file_type="a"
            ))
            print(order.text)
        """
        await self._prepare_session(request.credentials, request.district_code)

        # Build proveido URL
        params = {
            "pidJuzgado": request.court_id,
            "sCodi": request.order_code,
            "nPosi": request.position,
            "sFile": request.file_type,
            "MT": "",
        }

        try:
            response = await self._client.get(
                self.PROVEIDO_PATH,
                params=params,
            )
        except Exception as e:
            raise MEVError(
                "Failed to fetch order",
                {"order_code": request.order_code, "error": str(e)},
            )

        # Parse order
        try:
            order = self._order_parser.parse(
                response.text,
                court_id=request.court_id,
                case_id="",  # Not available in this request
                order_code=request.order_code,
                position=request.position,
            )
        except Exception as e:
            raise ParseError(
                "Failed to parse order",
                {"error": str(e)},
            )

        if order is None:
            raise NotFoundError(
                "Order not found or has no content",
                {"order_code": request.order_code, "position": request.position},
            )

        return order

    # =========================================================================
    # CONVENIENCE METHODS
    # =========================================================================

    async def search_by_case_number(
        self,
        credentials: Credentials,
        district_code: str,
        court_id: str,
        case_number: str,
    ) -> list[CourtFile]:
        """
        Convenience method to search by case number.

        Args:
            credentials: User credentials
            district_code: District tracking code
            court_id: Court identifier
            case_number: Case number to search

        Returns:
            List of matching CourtFile objects
        """
        request = SearchFilesRequest(
            credentials=credentials,
            district_code=district_code,
            court_id=court_id,
            search_option=SearchOption.BY_NUMBER,
            radio_option=RadioOption.BY_CASE_NUMBER,
            case_number=case_number,
        )
        return await self.search_files(request)

    async def search_by_caption(
        self,
        credentials: Credentials,
        district_code: str,
        court_id: str,
        caption: str,
    ) -> list[CourtFile]:
        """
        Convenience method to search by case caption.

        Args:
            credentials: User credentials
            district_code: District tracking code
            court_id: Court identifier
            caption: Case caption text to search

        Returns:
            List of matching CourtFile objects
        """
        request = SearchFilesRequest(
            credentials=credentials,
            district_code=district_code,
            court_id=court_id,
            search_option=SearchOption.BY_CAPTION,
            case_caption=caption,
        )
        return await self.search_files(request)

    async def download_causa_context(
        self, request: CourtFileRequest, order_timeout: float = 60.0,
    ) -> CausaContext:
        """
        Download a causa with all order texts for AI context.

        Fetches the causa file, then reads the full text of each order.
        This is used for causa tracking to provide context to AI.

        Args:
            request: File request with credentials and identifiers
            order_timeout: Timeout in seconds for each individual order download.
                If an order exceeds this timeout, it is skipped with empty content.

        Returns:
            CausaContext with file info and all order texts

        Raises:
            AuthenticationError: If authentication fails
            NotFoundError: If file is not found
            ParseError: If parsing fails

        Example:
            context = await service.download_causa_context(CourtFileRequest(
                credentials=Credentials(username="user", password="pass"),
                district_code="80",
                court_id="GAM2078",
                case_id="1281688"
            ))
            print(f"Fetched {context.order_count} orders")
        """
        # Step 1: Download file with all order summaries
        full_file = await self.download_file(request)

        # Step 2: Fetch full text for each order (with per-order timeout)
        orders_with_text: list[OrderWithText] = []

        for order_summary in full_file.orders:
            order_request = FileOrderRequest(
                credentials=request.credentials,
                district_code=request.district_code,
                court_id=request.court_id,
                order_code=order_summary.order_code,
                position=order_summary.position,
                file_type=order_summary.file_type,
            )

            try:
                order_detail = await asyncio.wait_for(
                    self.read_order(order_request),
                    timeout=order_timeout,
                )
                orders_with_text.append(
                    OrderWithText(
                        date=order_detail.date,
                        title=order_detail.title,
                        text=order_detail.text,
                        order_code=order_summary.order_code,
                        position=order_summary.position,
                        signed_by=order_detail.signed_by,
                        fojas=order_summary.fojas,
                    )
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Order {order_summary.order_code} timed out after {order_timeout}s, skipping"
                )
                orders_with_text.append(
                    OrderWithText(
                        date=order_summary.date,
                        title=order_summary.title,
                        text="",
                        order_code=order_summary.order_code,
                        position=order_summary.position,
                        fojas=order_summary.fojas,
                        error=f"Timed out after {order_timeout}s",
                    )
                )
            except Exception as e:
                # Include error info but continue with other orders
                orders_with_text.append(
                    OrderWithText(
                        date=order_summary.date,
                        title=order_summary.title,
                        text="",
                        order_code=order_summary.order_code,
                        position=order_summary.position,
                        fojas=order_summary.fojas,
                        error=str(e),
                    )
                )

        return CausaContext(
            file=full_file.file,
            orders=orders_with_text,
            court_name=full_file.court_name,
            district_name=full_file.district_name,
        )
