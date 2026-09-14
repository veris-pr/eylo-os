"""Shared Atlassian Cloud protocol constants used by Jira and Confluence."""

ATLASSIAN_API_ORIGIN = "https://api.atlassian.com"
ATLASSIAN_AUTHORIZATION_URL = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_AUTHORIZATION_PARAMS = (
    ("audience", "api.atlassian.com"),
    ("prompt", "consent"),
)
ATLASSIAN_INSTANCE_HOST_SUFFIX = "atlassian.net"
ATLASSIAN_INSTANCE_HOST_SUFFIXES = (ATLASSIAN_INSTANCE_HOST_SUFFIX,)


__all__ = [
    "ATLASSIAN_API_ORIGIN",
    "ATLASSIAN_AUTHORIZATION_PARAMS",
    "ATLASSIAN_AUTHORIZATION_URL",
    "ATLASSIAN_INSTANCE_HOST_SUFFIX",
    "ATLASSIAN_INSTANCE_HOST_SUFFIXES",
    "ATLASSIAN_TOKEN_URL",
]
