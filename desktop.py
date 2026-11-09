"""Launch the existing IFC Relay UI with an in-process desktop bridge."""

import asyncio
from contextlib import contextmanager
from email.message import Message
import json
import os
from pathlib import Path
from shutil import copyfile, copytree
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import Lock
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import webview

ROOT = Path(__file__).resolve().parent
HOST = "ifc-relay.invalid"
ORIGIN = f"https://{HOST}"
PAGE = f"{ORIGIN}/static/index.html"
# WebView2 skips WebResourceRequested for mapped virtual hosts.
GEOMETRY_PREFIX = "https://ifc-relay-geometry.invalid/cache/"
OUTPUT_ROUTES = (
    "/api/ifc/semantic/download", "/api/ifc/semantic/engine-download",
    "/api/build/latest/download", "/api/build/latest/report",
    "/api/build/latest/validation", "/api/build/latest/log",
)


def json_response(status, payload):
    return {"status": status, "contentType": "application/json", "body": json.dumps(payload)}


class DisabledHttpServer:
    @classmethod
    def start_server(cls, *_args, **_kwargs):
        raise RuntimeError("The Desktop HTTP server is disabled")


class DesktopBridge:
    def __init__(self):
        self._window = None
        self._geometry = {}
        self._geometry_streams = {}
        self._geometry_lock = Lock()
        self._activity_lock = Lock()
        self._active = 0
        self._closing = False

    @contextmanager
    def _working(self):
        with self._activity_lock:
            if self._closing:
                raise RuntimeError("Desktop is closing")
            self._active += 1
        try:
            yield
        finally:
            with self._activity_lock:
                self._active -= 1

    def _can_close(self):
        with self._activity_lock:
            busy = self._active > 0
            if not busy:
                self._closing = True
        if busy:
            self._window.run_js("setMessage('กำลังประมวลผล · รอให้งานเสร็จก่อนปิดโปรแกรม');")
            return False
        return True

    def import_ifc(self, carry_selection):
        with self._working():
            return self._import_ifc(carry_selection)

    def _import_ifc(self, carry_selection):
        paths = self._window.create_file_dialog(
            webview.FileDialog.OPEN, file_types=("IFC files (*.ifc)",),
        )
        if not paths:
            return None

        self._window.run_js("setMessage('กำลังอ่านและตรวจไฟล์ IFC ที่เลือก...');")
        from fastapi import HTTPException, UploadFile
        from app import import_file

        path = Path(paths[0])
        try:
            source = path.open("rb")
        except OSError:
            return json_response(400, {"detail": "อ่านไฟล์ IFC ที่เลือกไม่ได้"})
        with source:
            try:
                result = asyncio.run(import_file(UploadFile(source, filename=path.name), carry_selection is True))
            except HTTPException as error:
                return json_response(error.status_code, {"detail": error.detail})
        return json_response(200, result)

    def request(self, method, path, body=None):
        if not isinstance(path, str):
            return json_response(404, {"detail": "Not Found"})
        url = urlsplit(path)
        if url.scheme or url.netloc or not url.path.startswith("/api/"):
            return json_response(404, {"detail": "Not Found"})
        with self._working():
            return asyncio.run(self._request(method, path, body))

    async def _dispatch(self, method, path, body=None):
        from app import app

        file_path = None

        async def capture_files(scope, receive, send):
            # FileResponse can hand off the existing cache file without reading it into HTTPX.
            scope["extensions"] = {"http.response.pathsend": {}}

            async def capture(message):
                nonlocal file_path
                if message["type"] == "http.response.pathsend":
                    file_path = message["path"]
                    message = {"type": "http.response.body", "body": b""}
                await send(message)

            await app(scope, receive, capture)

        transport = httpx.ASGITransport(
            app=capture_files, raise_app_exceptions=False,
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = {"Content-Type": "application/json"} if body is not None else None
            response = await client.request(method, path, content=body, headers=headers)
        return response, file_path

    async def _request(self, method, path, body):
        response, file_path = await self._dispatch(method, path, body)
        if file_path is not None and response.is_success:
            token = uuid4().hex
            with self._geometry_lock:
                if len(self._geometry) == 16:
                    self._geometry.pop(next(iter(self._geometry)))
                self._geometry[token] = file_path
            return {"fileUrl": GEOMETRY_PREFIX + token}
        return {
            "status": response.status_code,
            "contentType": response.headers.get("content-type", ""),
            "body": response.text,
        }

    def save_output(self, output):
        with self._working():
            return self._save_output(output)

    def _save_output(self, output):
        from fastapi import HTTPException

        if output in ("manifest", "checklist"):
            from app import current_build_result_or_404

            try:
                result = current_build_result_or_404()
            except HTTPException as error:
                return json_response(error.status_code, {"detail": error.detail})
            source = Path(result.get(f"{output}_path") or "")
            filename = source.name
        elif output in OUTPUT_ROUTES:
            response, file_path = asyncio.run(self._dispatch("GET", output))
            if not response.is_success or file_path is None:
                return {
                    "status": response.status_code, "contentType": response.headers.get("content-type", ""),
                    "body": response.text,
                }
            source = Path(file_path)
            disposition = Message()
            disposition["content-disposition"] = response.headers.get("content-disposition", "")
            filename = disposition.get_filename() or source.name
        else:
            return json_response(404, {"detail": "Not Found"})

        if not source.is_file():
            return json_response(404, {"detail": "ไม่พบไฟล์ผลลัพธ์ที่สร้างไว้"})
        selected = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename)
        if not selected:
            return json_response(200, {"status": "cancelled"})
        destination = Path(selected if isinstance(selected, str) else selected[0])
        temporary = None
        try:
            if destination.resolve() != source.resolve():
                with NamedTemporaryFile(dir=destination.parent, prefix=".ifc-relay-", suffix=".tmp", delete=False) as file:
                    temporary = Path(file.name)
                copyfile(source, temporary)
                os.replace(temporary, destination)
        except OSError as error:
            return json_response(500, {"detail": f"บันทึกไฟล์ไม่สำเร็จ: {error}"})
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return json_response(200, {"status": "saved", "path": str(destination)})

    def _serve_geometry(self, sender, args):
        from System.IO import FileAccess, FileMode, FileShare, FileStream, IOException

        token = str(args.Request.Uri).removeprefix(GEOMETRY_PREFIX)
        headers = args.Request.Headers
        cors = f"Access-Control-Allow-Origin: {ORIGIN}\r\nCache-Control: no-store"
        if args.Request.Method == "GET" and headers.Contains("Origin") and headers.GetHeader("Origin") == ORIGIN:
            with self._geometry_lock:
                path = self._geometry.pop(token, None)
            if path:
                try:
                    stream = FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete)
                except IOException:
                    pass
                else:
                    with self._geometry_lock:
                        self._geometry_streams[token] = stream
                    args.Response = sender.Environment.CreateWebResourceResponse(
                        stream, 200, "OK", cors + "\r\nContent-Type: application/json",
                    )
                    return
        args.Response = sender.Environment.CreateWebResourceResponse(None, 404, "Not Found", cors)

    def release_geometry(self, file_url):
        if not isinstance(file_url, str) or not file_url.startswith(GEOMETRY_PREFIX):
            return
        token = file_url.removeprefix(GEOMETRY_PREFIX)
        with self._geometry_lock:
            self._geometry.pop(token, None)
            stream = self._geometry_streams.pop(token, None)
        # WebView2 does not dispose a response stream after reading it.
        if stream is not None:
            stream.Dispose()


def mount_page(window, assets, bridge):
    if not window.events.loaded.wait(60):
        print("WebView2 did not finish initialization.", flush=True)
        window.destroy()
        return

    from Microsoft.Web.WebView2.Core import CoreWebView2HostResourceAccessKind, CoreWebView2WebResourceContext
    from System import Action

    def allow_app_page(_sender, navigation):
        navigation.Cancel = str(navigation.Uri) != PAGE

    def map_assets():
        core = window.native.browser.webview.CoreWebView2
        core.SetVirtualHostNameToFolderMapping(HOST, str(assets), CoreWebView2HostResourceAccessKind.Deny)
        core.NavigationStarting += allow_app_page
        core.AddWebResourceRequestedFilter(GEOMETRY_PREFIX + "*", CoreWebView2WebResourceContext.All)
        core.WebResourceRequested += bridge._serve_geometry

    window.native.Invoke(Action(map_assets))
    window.load_url(PAGE)


def main():
    os.environ.pop("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", None)
    os.environ.pop("WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER", None)
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    webview.settings["REMOTE_DEBUGGING_PORT"] = None

    with TemporaryDirectory(prefix="ifc-relay-desktop-", ignore_cleanup_errors=True) as directory:
        scratch = Path(directory)
        assets = scratch / "assets"
        copytree(ROOT / "static", assets / "static")

        bridge = DesktopBridge()
        window = webview.create_window(
            "IFC Relay — Desktop",
            html="<p>Starting IFC Relay...</p>",
            js_api=bridge,
            width=1440,
            height=900,
            server=DisabledHttpServer,
        )
        bridge._window = window
        window.events.initialized += lambda renderer: renderer == "edgechromium"
        window.events.closing += bridge._can_close
        webview.start(
            mount_page,
            args=(window, assets, bridge),
            gui="edgechromium",
            debug=False,
            http_server=False,
            private_mode=True,
            storage_path=str(scratch / "profile"),
            server=DisabledHttpServer,
        )
        if webview.renderer != "edgechromium":
            raise SystemExit("IFC Relay Desktop requires Microsoft Edge WebView2 Runtime.")


if __name__ == "__main__":
    main()
