import socket
from urllib.parse import urlparse
import ipaddress
import structlog

logger = structlog.get_logger(__name__)

def is_safe_url(url: str) -> bool:
    """
    Check if a URL is safe to request from the server (SSRF protection).
    - Must use HTTPS.
    - Hostname must not resolve to a private, loopback, or link-local IP.
    """
    if not url:
        return False

    parsed = urlparse(url)
    if parsed.scheme != "https":
        logger.warning("unsafe_url_scheme", url=url, scheme=parsed.scheme)
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    try:
        # Resolve hostname to IPs
        # Note: In a production environment with high scale, you might want to 
        # use an async resolver or cache results, but for escalation webhooks
        # (low frequency) this is acceptable.
        ips = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in ips:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
                logger.warning("unsafe_url_ip", url=url, ip=ip_str)
                return False
                
        return True
    except socket.gaierror:
        logger.warning("url_resolution_failed", url=url)
        # If we can't resolve it, we can't verify it's safe. 
        # In strict environments, return False.
        return False
    except Exception as exc:
        logger.error("url_safety_check_error", url=url, error=str(exc))
        return False
