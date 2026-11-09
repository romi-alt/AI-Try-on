import io
import re
import uuid

from PIL import Image

from app.core.config import settings
from tests.helpers import exif_with_gps, make_image_bytes, make_session

KEY_RE = r"^captures/{sid}/[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}\.webp$"


def upload(api, session_id, data: bytes, name="photo.jpg", content_type="image/jpeg"):
    return api.post("/capture", data={"session_id": session_id}, files={"file": (name, data, content_type)})


async def test_capture_is_validated_stored_and_its_key_returned(api, s3):
    sid = await make_session(api)

    r = await upload(api, sid, make_image_bytes(800, 1200))

    assert r.status_code == 201, r.text
    body = r.json()
    assert re.match(KEY_RE.format(sid=sid), body["key"])
    assert (body["width"], body["height"]) == (800, 1200)
    assert body["content_type"] == "image/webp" and body["expires_in_seconds"] == 3600
    obj = s3.get_object(Bucket=settings.s3_bucket, Key=body["key"])
    stored = obj["Body"].read()
    assert obj["ContentType"] == "image/webp"
    assert obj["CacheControl"] == "private, no-store"
    assert obj["Metadata"]["session-id"] == sid and "expires-at" in obj["Metadata"]
    assert body["size_bytes"] == len(stored)
    assert Image.open(io.BytesIO(stored)).format == "WEBP"


async def test_stored_object_has_no_exif(api, s3):
    sid = await make_session(api)
    original = make_image_bytes(800, 1200, exif=exif_with_gps())

    r = await upload(api, sid, original)

    stored = s3.get_object(Bucket=settings.s3_bucket, Key=r.json()["key"])["Body"].read()
    assert b"SecretCameraCo" not in stored and b"EXIF" not in stored
    assert len(Image.open(io.BytesIO(stored)).getexif()) == 0


async def test_webp_upload_is_accepted(api, s3):
    sid = await make_session(api)
    r = await upload(api, sid, make_image_bytes(800, 1200, "WEBP"), "p.webp", "image/webp")
    assert r.status_code == 201


async def test_each_upload_gets_a_distinct_key_under_the_session_prefix(api, s3):
    sid = await make_session(api)
    a = await upload(api, sid, make_image_bytes())
    b = await upload(api, sid, make_image_bytes())
    assert a.json()["key"] != b.json()["key"]
    listed = s3.list_objects_v2(Bucket=settings.s3_bucket, Prefix=f"captures/{sid}/")
    assert listed["KeyCount"] == 2


async def test_orientation_flag_is_honoured(api, s3):
    sid = await make_session(api)
    r = await upload(api, sid, make_image_bytes(1200, 800, exif=exif_with_gps(orientation=6)))
    assert r.status_code == 201 and (r.json()["width"], r.json()["height"]) == (800, 1200)


async def test_rejected_images_are_not_stored(api, s3):
    sid = await make_session(api)
    cases = {
        "landscape": (make_image_bytes(1200, 800), 422),
        "too short": (make_image_bytes(400, 700), 422),
        "png": (make_image_bytes(800, 1200, "PNG"), 415),
        "text": (b"not an image at all", 415),
        "empty": (b"", 422),
    }
    for name, (data, expected) in cases.items():
        r = await upload(api, sid, data)
        assert r.status_code == expected, (name, r.text)
        assert r.json()["detail"]
    assert s3.list_objects_v2(Bucket=settings.s3_bucket).get("KeyCount", 0) == 0


async def test_content_type_header_is_not_trusted(api, s3):
    sid = await make_session(api)
    r = await upload(api, sid, b"<script>alert(1)</script>", "evil.jpg", "image/jpeg")
    assert r.status_code == 415
    ok = await upload(api, sid, make_image_bytes(), "photo.bin", "application/octet-stream")
    assert ok.status_code == 201


async def test_file_over_5mb_is_rejected_by_the_route(api, s3):
    sid = await make_session(api)
    just_over = b"\xff\xd8" + b"\x00" * (settings.capture_max_bytes - 1)  # 5 MB + 1 byte

    r = await upload(api, sid, just_over)

    assert r.status_code == 413 and "5 MB" in r.json()["detail"]
    assert s3.list_objects_v2(Bucket=settings.s3_bucket).get("KeyCount", 0) == 0


async def test_file_exactly_at_the_limit_is_not_a_size_error(api, s3):
    sid = await make_session(api)
    r = await upload(api, sid, b"\xff\xd8" + b"\x00" * (settings.capture_max_bytes - 2))
    assert r.status_code == 415  # past the size gate; fails later as "not a decodable image"


async def test_huge_upload_is_cut_off_by_the_body_limit_middleware(api, s3):
    sid = await make_session(api)

    r = await upload(api, sid, b"\x00" * (settings.capture_max_bytes + 200_000))

    assert r.status_code == 413 and "larger than" in r.json()["detail"]


async def test_streamed_upload_without_content_length_is_also_cut_off(api, s3):
    sid = await make_session(api)
    boundary = "xBOUNDARYx"
    chunk = b"\x00" * 65536

    async def body():  # chunked: no Content-Length for the server to check up front
        yield (
            f'--{boundary}\r\nContent-Disposition: form-data; name="session_id"\r\n\r\n{sid}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode()
        for _ in range(100):  # ~6.5 MB
            yield chunk
        yield f"\r\n--{boundary}--\r\n".encode()

    r = await api.post(
        "/capture", content=body(), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )

    assert r.status_code == 413


async def test_unknown_session_is_404(api, s3):
    r = await upload(api, str(uuid.uuid4()), make_image_bytes())
    assert r.status_code == 404 and s3.list_objects_v2(Bucket=settings.s3_bucket).get("KeyCount", 0) == 0


async def test_missing_or_malformed_fields_are_422(api, s3):
    sid = await make_session(api)
    img = make_image_bytes()
    assert (await api.post("/capture", data={"session_id": sid})).status_code == 422
    assert (await api.post("/capture", files={"file": ("a.jpg", img, "image/jpeg")})).status_code == 422
    assert (await upload(api, "not-a-uuid", img)).status_code == 422


async def test_storage_outage_is_a_503_not_a_500(api, s3, monkeypatch):
    sid = await make_session(api)
    monkeypatch.setattr(settings, "s3_endpoint_url", "http://127.0.0.1:1")
    from app.core import storage

    storage.internal_client.cache_clear()

    r = await upload(api, sid, make_image_bytes())

    assert r.status_code == 503 and "photo" in r.json()["detail"]
