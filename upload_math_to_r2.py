"""Upload math competition files (static/uploads/10/) to Cloudflare R2.

使用前设置环境变量:
  CYJY_R2_ACCESS_KEY  - R2 Access Key ID
  CYJY_R2_SECRET_KEY  - R2 Secret Access Key
  CYJY_R2_ACCOUNT_ID  - Cloudflare Account ID
  CYJY_R2_BUCKET      - R2 bucket name (默认: chongyue-math)

用法:
  pip install boto3
  set CYJY_R2_ACCESS_KEY=xxx
  set CYJY_R2_SECRET_KEY=xxx
  set CYJY_R2_ACCOUNT_ID=xxx
  python upload_math_to_r2.py
"""

import os
import sys
import hashlib
import base64
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# pip install boto3
try:
    import boto3
    from botocore.config import Config
except ImportError:
    print("请先安装 boto3: pip install boto3")
    sys.exit(1)

# ── R2 配置 ──────────────────────────────────────────
ACCESS_KEY = os.environ.get("CYJY_R2_ACCESS_KEY", "")
SECRET_KEY = os.environ.get("CYJY_R2_SECRET_KEY", "")
ACCOUNT_ID = os.environ.get("CYJY_R2_ACCOUNT_ID", "")
BUCKET = os.environ.get("CYJY_R2_BUCKET", "chongyue-math")

ENDPOINT = f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com"
PUBLIC_URL = f"https://pub-{hashlib.md5(ACCOUNT_ID.encode()).hexdigest()[:16]}.r2.dev" if ACCOUNT_ID else ""

# ── 本地文件目录 ──────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
MATH_DIR = BASE_DIR / "static" / "uploads" / "10"

# ══════════════════════════════════════════════════════

def verify_config():
    """检查必要的环境变量和文件目录。"""
    errors = []
    for name, val in [("CYJY_R2_ACCESS_KEY", ACCESS_KEY),
                       ("CYJY_R2_SECRET_KEY", SECRET_KEY),
                       ("CYJY_R2_ACCOUNT_ID", ACCOUNT_ID)]:
        if not val:
            errors.append(f"缺少环境变量: {name}")
    if not MATH_DIR.exists():
        errors.append(f"数学竞赛目录不存在: {MATH_DIR}")
    if errors:
        print("❌ 配置错误:")
        for e in errors:
            print(f"   {e}")
        print()
        print("请设置以下环境变量后重试:")
        print("  set CYJY_R2_ACCESS_KEY=<你的 R2 Access Key ID>")
        print("  set CYJY_R2_SECRET_KEY=<你的 R2 Secret Access Key>")
        print("  set CYJY_R2_ACCOUNT_ID=<你的 Cloudflare Account ID>")
        return False
    return True


def get_s3_client():
    """创建 S3 兼容客户端 (指向 R2)。"""
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        config=Config(
            region_name="auto",
            retries={"max_attempts": 3},
        ),
    )


def upload_file(s3, file_path: Path, rel_path: str):
    """上传单个文件到 R2。"""
    try:
        content_type = "application/octet-stream"
        ext = file_path.suffix.lower()
        if ext == ".pdf":
            content_type = "application/pdf"
        elif ext in (".zip",):
            content_type = "application/zip"
        elif ext in (".rar",):
            content_type = "application/x-rar-compressed"

        s3.upload_file(
            str(file_path),
            BUCKET,
            rel_path,
            ExtraArgs={"ContentType": content_type},
        )
        size_mb = file_path.stat().st_size / (1024 * 1024)
        return (True, rel_path, size_mb, None)
    except Exception as e:
        return (False, rel_path, 0, str(e))


def main():
    if not verify_config():
        return 1

    print("=" * 60)
    print("  数学竞赛文件上传 → Cloudflare R2")
    print("=" * 60)
    print(f"  Bucket: {BUCKET}")
    print(f"  Endpoint: {ENDPOINT}")
    print(f"  Public URL: {PUBLIC_URL}")
    print(f"  Source: {MATH_DIR}")
    print()

    # ── 收集所有文件 ──────────────────────────────
    files = []
    for f in sorted(MATH_DIR.rglob("*")):
        if f.is_file():
            rel = f.relative_to(MATH_DIR).as_posix()
            files.append((f, rel))

    total_size = sum(f[0].stat().st_size for f in files)
    print(f"📁 共 {len(files)} 个文件，{total_size / (1024**3):.1f} GB")
    print()

    # ── 连接 S3 ──────────────────────────────────
    print("🔗 连接 R2...")
    try:
        s3 = get_s3_client()
        s3.head_bucket(Bucket=BUCKET)
        print(f"   Bucket '{BUCKET}' 已存在 ✅")
    except Exception as e:
        print(f"   Bucket 不存在或无法访问: {e}")
        print("   请在 Cloudflare 控制台创建 R2 Bucket: " + BUCKET)
        return 1
    print()

    # ── 并发上传 ──────────────────────────────────
    print(f"⬆️  开始上传 (并发 5 线程)...")
    success = 0
    failed = 0
    uploaded_bytes = 0
    workers = min(10, max(2, len(files) // 50))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(upload_file, s3, fp, rel): rel
                   for fp, rel in files}
        for i, future in enumerate(as_completed(futures), 1):
            ok, rel, size_mb, err = future.result()
            if ok:
                success += 1
                uploaded_bytes += size_mb
                pct = i / len(files) * 100
                print(f"   [{i}/{len(files)} {pct:.0f}%] ✅ {rel} ({size_mb:.1f}MB)")
            else:
                failed += 1
                print(f"   [{i}/{len(files)}] ❌ {rel}: {err}")

    print()
    print("=" * 60)
    print(f"  完成: {success} 成功, {failed} 失败")
    print(f"  上传: {uploaded_bytes / 1024:.1f} GB")
    print("=" * 60)
    print()
    print("📌 下一步：设置 Render 环境变量使公网可访问:")
    print(f"   CYJY_R2_PUBLIC_URL = https://{BUCKET}.{ACCOUNT_ID}.r2.cloudflarestorage.com")
    print()
    print("   或者绑定自定义域名后使用:")
    print(f"   CYJY_R2_PUBLIC_URL = https://math.你的域名.com")
    print()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
