"""Media/file native tool handlers (RFC-001 Phase 5b).

Verbatim moves from OdinBot: browser_screenshot, generate_file, post_file,
analyze_image (returns the ``__image_block__`` marker dict the tool loop
injects as vision content), generate_image, and the image-magic sniffing
helper. ``get_config`` is a provider callable (config hot-reload).
"""

from __future__ import annotations

import base64
import os
from collections.abc import Callable

from ...odin_log import get_logger
from ...tools.execution_outcome import ToolFailure

log = get_logger("media")

# Hard cap on a URL-fetched image so a huge or hostile body can't exhaust memory.
_ANALYZE_IMAGE_MAX_BYTES = 25 * 1024 * 1024  # 25 MiB
_DELIVERY_UNAVAILABLE = "Conversation artifact publication is unavailable until Phase 2."


class MediaTools:
    def __init__(
        self,
        *,
        get_config: Callable,
        browser_manager,
        tool_executor,
        image_selector=None,
    ) -> None:
        self.get_config = get_config
        self.browser_manager = browser_manager
        self.tool_executor = tool_executor
        self.image_selector = image_selector

    @staticmethod
    def _delivery_available() -> bool:
        """No durable conversation publisher is wired in Phase 1."""
        return False

    @staticmethod
    async def _publish_attachment(request, data: bytes, filename: str, caption: str = ""):
        """Phase 2 must supply invocation-owned durable artifact publication.

        A renderer connection or an in-memory queue is not a publication receipt.
        """
        raise NotImplementedError(_DELIVERY_UNAVAILABLE)

    def _retain_generated_image(self, data: bytes, folder: str = "generated-images") -> str | None:
        """A local copy of a posted image the model can open again; Desktop keeps one."""
        return None

    @staticmethod
    def _detect_image_type(data: bytes) -> str | None:
        """Detect image media type from file magic bytes."""
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if data[:2] == b"\xff\xd8":
            return "image/jpeg"
        if data[:4] == b"GIF8":
            return "image/gif"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        return None

    async def _handle_browser_screenshot(self, message, inp: dict) -> str:
        """Take a browser screenshot and post it as a conversation image."""
        if not self.browser_manager:
            return ToolFailure(
                "Browser automation is not enabled. Set browser.enabled=true in config."
            )
        from ...tools.browser import handle_browser_screenshot

        try:
            text, screenshot_bytes = await handle_browser_screenshot(self.browser_manager, inp)
            if screenshot_bytes:
                await self._publish_attachment(message, screenshot_bytes, "screenshot.png")
                # As for generated images: the posted copy is the conversation's; a
                # local copy is the one the model can open again (Desktop keeps one).
                local_copy = None
                try:
                    local_copy = self._retain_generated_image(screenshot_bytes, "screenshots")
                except OSError as e:
                    log.info("screenshot posted but no local copy was kept: %s", e)
                if local_copy:
                    text += f"\nLocal file on localhost: {local_copy}"
            return text
        except Exception as e:
            return ToolFailure(f"Browser screenshot failed: {e}")

    async def _handle_generate_file(self, message, inp: dict) -> str:
        """Generate a file from content and post it as a conversation attachment."""
        filename = inp.get("filename", "output.txt")
        content = inp.get("content", "")
        caption = inp.get("caption", "")

        file_bytes = content.encode("utf-8")
        try:
            await self._publish_attachment(message, file_bytes, filename, caption)
            return f"File `{filename}` ({len(file_bytes)} bytes) attached to conversation."
        except Exception as e:
            return ToolFailure(f"Failed to post file: {e}")

    async def _handle_post_file(self, message, inp: dict) -> str:
        """Fetch a file from a host and post it to the conversation.

        For localhost this reads directly from the local filesystem; for any
        other host it falls back to SSH + base64 stream (handles binary safely).
        Bypassing SSH for localhost avoids the host-key / ssh_key_path gauntlet
        when Odin wants to post its own files.
        """
        host_alias = inp.get("host")
        path = inp.get("path")
        caption = inp.get("caption", "")

        if not host_alias or not path:
            return ToolFailure("Both 'host' and 'path' are required.")

        requester_id = getattr(message, "owner_id", None)
        if not isinstance(requester_id, str) or not requester_id:
            return ToolFailure("Permission denied: authenticated owner identity is required.")
        lease = self.tool_executor.acquire_host_for_user(host_alias, requester_id)
        if not lease:
            return ToolFailure(f"Unknown or disallowed host: {host_alias}")
        try:
            target = lease.target
            address, ssh_user = target.address, target.ssh_user

            # Local fast path — no SSH gymnastics needed.
            from ...tools.ssh import is_local_address

            if is_local_address(address):
                try:
                    with open(path, "rb") as f:
                        file_bytes = f.read()
                except FileNotFoundError:
                    return ToolFailure(f"File not found: {path}")
                except PermissionError:
                    return ToolFailure(f"Permission denied reading file: {path}")
                except OSError as exc:
                    return ToolFailure(f"Failed to read file: {exc}")
            else:
                try:
                    from ...tools.binary_read import read_binary_file

                    file_bytes, read_error = await lease.run(
                        lambda: read_binary_file(
                            address,
                            path,
                            max_bytes=25 * 1024 * 1024 + 1,
                            ssh_key_path=target.key_path,
                            known_hosts_path=target.known_hosts_path,
                            ssh_user=ssh_user,
                            port=target.port,
                            host_key_alias=target.host_key_alias,
                        )
                    )
                    if read_error or file_bytes is None:
                        return ToolFailure(f"Failed to fetch file: {read_error}")
                except TimeoutError:
                    return ToolFailure("File fetch timed out (30s).")
                except Exception as e:
                    return ToolFailure(f"Failed to fetch file: {e}")
        finally:
            lease.release()

        if not file_bytes:
            return ToolFailure(f"File not found or empty: {path}")

        # Size check (conversation attachment limit: 25MB)
        if len(file_bytes) > 25 * 1024 * 1024:
            return (
                f"File too large to post ({len(file_bytes) / 1024 / 1024:.1f} MB). "
                "Conversation attachment limit is 25 MB."
            )

        filename = os.path.basename(path)
        try:
            await self._publish_attachment(message, file_bytes, filename, caption)
            return f"Posted `{filename}` ({len(file_bytes) / 1024:.1f} KB) to conversation."
        except Exception as e:
            return ToolFailure(f"Failed to upload to the conversation: {e}")

    async def _handle_analyze_image(self, message, inp: dict) -> str | dict:
        """Fetch an image and return a vision block for the LLM to analyze.

        Returns either an error string or a dict with ``__image_block__`` key
        that the tool loop injects as a vision content block.
        """
        url = inp.get("url")
        host = inp.get("host")
        path = inp.get("path")
        prompt = inp.get("prompt", "Describe this image in detail.")

        image_bytes: bytes | None = None

        if url:
            # Validate URL scheme to prevent SSRF via file://, ftp://, etc.
            if not url.startswith(("http://", "https://")):
                return ToolFailure("Only http:// and https:// URLs are supported.")
            # Hardened transport with redirects DISABLED (images never need to
            # follow one): per-hop SSRF validation, pinned connect IP, TLS
            # verification, and a byte cap. Scheme-only validation was not
            # SSRF-safe (http://169.254.169.254/... passed it).
            from ...tools.safe_fetch import (
                BlockedAddressError,
                ResponseTooLargeError,
                safe_fetch,
            )

            try:
                resp = await safe_fetch(
                    url,
                    follow_redirects=False,
                    max_bytes=_ANALYZE_IMAGE_MAX_BYTES,
                    timeout=30.0,
                )
            except BlockedAddressError:
                return ToolFailure(
                    "URL blocked: targets a private, loopback, link-local, "
                    "or cloud-metadata address (SSRF protection)."
                )
            except ResponseTooLargeError:
                return ToolFailure(f"Image too large (max {_ANALYZE_IMAGE_MAX_BYTES} bytes).")
            except Exception as e:
                return ToolFailure(f"Failed to fetch image from URL: {e}")
            if resp.status != 200:
                return ToolFailure(f"Failed to fetch image from URL (HTTP {resp.status})")
            ct = resp.content_type
            if not ct.startswith("image/"):
                return ToolFailure(f"URL does not point to an image (Content-Type: {ct})")
            image_bytes = resp.body
        elif host and path:
            # Fetch from host as bounded raw bytes

            requester_id = getattr(message, "owner_id", None)
            if not isinstance(requester_id, str) or not requester_id:
                return ToolFailure("Permission denied: authenticated owner identity is required.")
            lease = self.tool_executor.acquire_host_for_user(host, requester_id)
            if not lease:
                return ToolFailure(f"Unknown or disallowed host: {host}")
            try:
                target = lease.target
                address, ssh_user = target.address, target.ssh_user
                # Same defect as analyze_pdf: base64 over the text pipeline is
                # truncated at MAX_OUTPUT_CHARS, so any image over roughly 12KB
                # arrived corrupt (adversarial review). Raw bounded bytes instead.
                from ...tools.binary_read import read_binary_file

                image_bytes, read_error = await lease.run(
                    lambda: read_binary_file(
                        address,
                        path,
                        max_bytes=_ANALYZE_IMAGE_MAX_BYTES,
                        ssh_key_path=target.key_path,
                        known_hosts_path=target.known_hosts_path,
                        ssh_user=ssh_user,
                        port=target.port,
                        host_key_alias=target.host_key_alias,
                    )
                )
            finally:
                lease.release()
            if read_error:
                return ToolFailure(f"Failed to read image from host: {read_error}")
        else:
            return ToolFailure("Provide either 'url' or both 'host' and 'path'.")

        if not image_bytes:
            return ToolFailure("No image data retrieved.")

        # Enforce 5MB image attachment limit
        if len(image_bytes) > 5 * 1024 * 1024:
            return ToolFailure("Image exceeds 5MB size limit.")

        media_type = self._detect_image_type(image_bytes)
        if not media_type:
            return ToolFailure("Unsupported image format. Supported: PNG, JPEG, GIF, WEBP.")

        b64 = base64.b64encode(image_bytes).decode("ascii")

        # Return a special marker dict that the tool loop will inject as a
        # vision content block.  The tool result text sent to the LLM will be
        # the prompt, while the image block gets appended to the next user
        # message so Codex can see it.
        return {
            "__image_block__": {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": b64,
                },
            },
            "__prompt__": prompt,
        }

    async def _handle_generate_image(self, message, inp: dict):
        """Generate an image via the selected backend and post as a conversation
        attachment. The backend returns bytes; this tool layer owns conversation delivery.

        Returns a ToolResult whose ``output`` is a generic user-facing string
        (never names the backend) plus ``audit_metadata`` — a bounded structured
        record so ``search_audit`` can answer "which backend?" when asked.
        """
        from ...tools.image import ImageGenError
        from ...tools.result_validator import ToolResult

        if self.image_selector is None:
            return ToolFailure("Image generation is not available.")

        prompt_text = inp.get("prompt", "")
        if not prompt_text:
            return ToolFailure("A 'prompt' describing the image is required.")
        removed = sorted({"size", "negative", "model", "width", "height"} & inp.keys())
        if removed:
            return ToolFailure("Unsupported image generation option(s): " + ", ".join(removed))

        # Do not incur a provider effect when durable publication is known unavailable.
        if not self._delivery_available():
            return ToolResult(
                output=_DELIVERY_UNAVAILABLE,
                ok=False,
                error="conversation_delivery_unavailable",
                tool_name="generate_image",
            )

        try:
            result = await self.image_selector.generate(prompt=prompt_text)
        except ImageGenError as e:
            # These messages are constructed to carry no payload/account data.
            return ToolFailure(f"Image generation failed: {e}")
        except Exception:
            # Never surface a raw provider payload; log without the body.
            log.warning("image generation raised unexpectedly", exc_info=True)
            return ToolFailure("Image generation failed unexpectedly.")

        # Non-sensitive structured record — enums + decoded dims only.
        meta: dict = {
            "backend": result.backend,
            "route": result.route,
            "fallback_reason": result.fallback_reason,
            "decoded_width": result.width,
            "decoded_height": result.height,
        }
        try:
            await self._publish_attachment(message, result.data, "generated.png")
        except Exception as e:
            # Generation succeeded even though delivery failed — record both.
            meta["delivery_status"] = "upload_failed"
            log.info("image generated (backend=%s) but upload failed: %s", result.backend, e)
            return ToolResult(
                output=(f"Failed to upload generated image to the conversation: {e}. "
                        "Generation already succeeded; do not regenerate automatically."),
                ok=False,
                error="image_delivery_failed",
                tool_name="generate_image",
                audit_metadata=meta,
            )

        meta["delivery_status"] = "posted"
        # Phase 2 artifacts need an authorized store reference, not a CDN URL.
        meta["attachment_url_available"] = False
        # Where Odin returns the attachment URL, Desktop returns a local copy so
        # analyze_image and post_file can use the image again.
        local_copy = None
        try:
            local_copy = self._retain_generated_image(result.data)
        except OSError as e:
            log.info("image posted but no local copy was kept: %s", e)
        meta["local_copy_available"] = local_copy is not None
        log.info(
            "image generated: backend=%s model=%s decoded=%dx%d route=%s",
            result.backend, result.image_model, result.width, result.height, result.route,
        )
        return ToolResult(
            output=(
                f"Image generated ({result.width}x{result.height}, "
                f"{len(result.data) / 1024:.1f} KB) and posted."
                + (f" Local file on localhost: {local_copy}" if local_copy else "")
            ),
            tool_name="generate_image",
            audit_metadata=meta,
        )
