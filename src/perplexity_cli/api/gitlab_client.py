"""GitLab API client for repository operations."""

from typing import Any

import httpx


class GitLabClient:
    """Client for interacting with GitLab API."""

    def __init__(self, token: str, gitlab_url: str = "https://gitlab.com") -> None:
        """Initialize GitLab client.

        Args:
            token: GitLab personal access token.
            gitlab_url: GitLab instance URL (default: https://gitlab.com).
        """
        self.token = token
        self.gitlab_url = gitlab_url.rstrip("/")
        self.api_base = f"{self.gitlab_url}/api/v4"

    def get_headers(self) -> dict[str, str]:
        """Get HTTP headers for GitLab API requests.

        Returns:
            Dictionary of HTTP headers including authentication.
        """
        return {
            "PRIVATE-TOKEN": self.token,
            "Content-Type": "application/json",
            "User-Agent": "perplexity-cli/0.1.0",
        }

    def list_user_projects(
        self,
        owned: bool = True,
        membership: bool = True,
        archived: bool = False,
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        """List user's GitLab projects/repositories.

        Args:
            owned: Include projects owned by the authenticated user.
            membership: Include projects where user is a member.
            archived: Include archived projects.
            per_page: Number of results per page (default: 100, max: 100).

        Returns:
            List of project dictionaries.

        Raises:
            httpx.HTTPStatusError: For HTTP errors (401, 403, 404, etc.).
            httpx.RequestError: For network/connection errors.
        """
        url = f"{self.api_base}/projects"
        params = {
            "owned": str(owned).lower(),
            "membership": str(membership).lower(),
            "archived": str(archived).lower(),
            "per_page": per_page,
            "simple": "true",  # Return only essential fields
            "order_by": "last_activity_at",
            "sort": "desc",
        }

        headers = self.get_headers()

        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(url, headers=headers, params=params)
                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 401:
                raise httpx.HTTPStatusError(
                    "Authentication failed. Token may be invalid or expired.",
                    request=e.request,
                    response=e.response,
                ) from e
            elif status == 403:
                raise httpx.HTTPStatusError(
                    "Access forbidden. Check token permissions.",
                    request=e.request,
                    response=e.response,
                ) from e
            else:
                raise

    def get_user_info(self) -> dict[str, Any]:
        """Get authenticated user information.

        Returns:
            User information dictionary.

        Raises:
            httpx.HTTPStatusError: For HTTP errors.
            httpx.RequestError: For network errors.
        """
        url = f"{self.api_base}/user"
        headers = self.get_headers()

        with httpx.Client(timeout=10) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
