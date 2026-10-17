"""个人 Base URL 的网络边界。只访问公网 HTTPS，且不跟随重定向。

不能只在保存时检查 DNS：域名之后可能改指向内网。因此每次连接都解析、检查，
再直接连接检查过的 IP；Host 与 TLS 证书校验仍使用原域名。默认模型不走这里。
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx


def validate_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        parts = urlsplit(value)
        port = parts.port
        host = parts.hostname
    except ValueError:
        raise ValueError("Base URL 格式不正确") from None
    if (
        parts.scheme != "https" or not host
        or parts.username is not None or parts.password is not None
        or parts.query or parts.fragment or port not in (None, 443)
        or "?" in value or "#" in value or "\\" in value
        or any(ord(c) < 33 or ord(c) == 127 for c in value)
    ):
        raise ValueError("Base URL 只支持公网 HTTPS（443 端口），不能包含账号、查询参数或片段")
    if host.lower() == "localhost" or host.lower().endswith((".localhost", ".local", ".internal")):
        raise ValueError("Base URL 不能指向本机或内网")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not _public_address(address):
        raise ValueError("Base URL 不能指向本机或内网")
    # 用 httpx 统一域名大小写、IDNA 和转义，保存与发送使用同一种格式。
    try:
        return str(httpx.URL(value)).rstrip("/")
    except httpx.InvalidURL:
        raise ValueError("Base URL 格式不正确") from None


def _public_address(address) -> bool:
    if not address.is_global or address.is_multicast:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        # 拒绝 IPv4 映射和隧道地址，避免表面公网、实际访问其他网络的转换。
        return not (address.ipv4_mapped or address.sixtofour or address.teredo)
    return True


def public_ip(host: str) -> str:
    try:
        addresses = list(dict.fromkeys(
            item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ))
    except OSError:
        raise ValueError("无法解析模型服务域名，请检查 Base URL") from None
    if not addresses or any(not _public_address(ipaddress.ip_address(ip)) for ip in addresses):
        raise ValueError("模型服务域名解析到了非公网地址，已拒绝连接")
    return addresses[0]


def _pinned_request(request: httpx.Request, address: str) -> httpx.Request:
    headers = request.headers.copy()
    headers["Host"] = request.url.netloc.decode("ascii")
    extensions = {**request.extensions, "sni_hostname": request.url.host}
    return httpx.Request(
        request.method, request.url.copy_with(host=address),
        headers=headers, stream=request.stream, extensions=extensions,
    )


class PublicModelTransport(httpx.AsyncBaseTransport):
    def __init__(self, base_url: str):
        self.base = httpx.URL(validate_base_url(base_url))
        self.inner = httpx.AsyncHTTPTransport(retries=0, trust_env=False)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if (request.url.scheme, request.url.host, request.url.port) != (
            self.base.scheme, self.base.host, self.base.port
        ):
            raise ValueError("拒绝向其他模型地址发送凭证")
        address = await asyncio.wait_for(asyncio.to_thread(public_ip, request.url.host), 10)
        return await self.inner.handle_async_request(_pinned_request(request, address))

    async def aclose(self):
        await self.inner.aclose()


class NoSyncModelTransport(httpx.BaseTransport):
    def handle_request(self, request):
        # 个人模型只允许走已经校验的异步通道，意外的同步调用直接失败。
        raise RuntimeError("个人模型请使用异步调用")
