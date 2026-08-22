import httpx


class HomeAssistantAdapter:
    def __init__(self, base_url: str, token: str | None = None, verify_tls: bool = True):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.verify_tls = verify_tls

    async def health_and_version(self) -> tuple[str, str | None]:
        async with httpx.AsyncClient(timeout=5, verify=self.verify_tls) as client:
            try:
                response = await client.get(f"{self.base_url}/api/config", headers=self.headers)
                response.raise_for_status()
                return "available", response.json().get("version")
            except (httpx.HTTPError, ValueError):
                return "unavailable", None

    async def entity_state(self, entity_id: str) -> dict:
        async with httpx.AsyncClient(timeout=5, verify=self.verify_tls) as client:
            response = await client.get(f"{self.base_url}/api/states/{entity_id}", headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def call_service(self, domain: str, service: str, data: dict) -> dict:
        allowed = {("light", "turn_on"), ("light", "turn_off"), ("switch", "turn_on"), ("switch", "turn_off")}
        if (domain, service) not in allowed:
            raise ValueError("Service call is outside the PoC allowlist")
        async with httpx.AsyncClient(timeout=10, verify=self.verify_tls) as client:
            response = await client.post(f"{self.base_url}/api/services/{domain}/{service}", headers=self.headers, json=data)
            response.raise_for_status()
            return response.json()

