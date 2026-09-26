"""把数学竞赛真题文件（static/uploads/10/）上传到 Cloudflare R2，供线上「数学竞赛真题库」在线阅读。

一次性准备（Cloudflare 控制台）:
  1. R2 → 创建 Bucket（默认名 chongyue-math）
  2. Bucket → Settings → Public access → 开启 "R2.dev subdomain"，
     记下形如 https://pub-xxxxxxxxxxxxxxxx.r2.dev 的公网地址（或绑定自己的域名）
  3. R2 → Manage R2 API Tokens → 创建带 "Object Read & Write" 权限的令牌，
     记下 Access Key ID / Secret Access Key，以及页面上的 Account ID

本地运行（Windows 示例，也可以把这些写进项目根目录的 .env 文件）:
  pip install boto3
  set CYJY_R2_ACCESS_KEY=<Access Key ID>
  set CYJY_R2_SECRET_KEY=<Secret Access Key>
  set CYJY_R2_ACCOUNT_ID=<Account ID>
  set CYJY_R2_PUBLIC_URL=https://pub-xxxxxxxxxxxxxxxx.r2.dev   (可选，仅用于最后的提示与自检)
  python upload_math_to_r2.py

参数:
  --catalog-only   只根据本地文件重新生成 math_catalog.json（含文件大小），不上传
  --force          即使云端已有同样大小的文件也重新上传

上传完成后:
  在 Render → Environment 添加 CYJY_MATH_FILES_URL=<上面的公网地址>，
  并提交更新后的 math_catalog.json，重新部署即可在线阅读。
"""

import os
import sys
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = Path(__file__).resolve().parent
MATH_DIR = BASE_DIR / "static" / "uploads" / "10"
CATALOG_PATH = BASE_DIR / "math_catalog.json"
HIDDEN = {".ds_store", "thumbs.db", "desktop.ini"}

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".rar": "application/vnd.rar",
    ".7z": "application/x-7z-compressed",
    ".csv": "text/csv; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def load_dotenv():
    """读取项目根目录 .env（不覆盖已存在的环境变量）。"""
    env = BASE_DIR / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def visible(path: Path) -> bool:
    return not path.name.startswith(".") and path.name.lower() not in HIDDEN


def collect_files():
    files = []
    for f in sorted(MATH_DIR.rglob("*")):
        if f.is_file() and visible(f):
            files.append((f, f.relative_to(MATH_DIR).as_posix()))
    return files


def write_catalog():
    """生成线上目录：每个年份文件夹一项，附带文件大小，供页面显示。"""
    years = []
    for d in sorted((p for p in MATH_DIR.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        pdfs, others, sizes = [], [], {}
        for f in sorted(d.rglob("*")):
            if not (f.is_file() and visible(f)):
                continue
            rel = f.relative_to(MATH_DIR).as_posix()
            (pdfs if f.suffix.lower() == ".pdf" else others).append(rel)
            sizes[rel] = f.stat().st_size
        years.append({"name": d.name, "pdfs": pdfs, "others": others,
                      "total": len(pdfs) + len(others), "sizes": sizes})
    CATALOG_PATH.write_text(json.dumps(years, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(y["total"] for y in years)
    print(f"📝 已更新 {CATALOG_PATH.name}：{len(years)} 个年份目录，{total} 个文件")


def get_s3_client(account_id, access_key, secret_key):
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(region_name="auto", retries={"max_attempts": 5, "mode": "standard"}),
    )


def remote_size(s3, bucket, key):
    try:
        return s3.head_object(Bucket=bucket, Key=key)["ContentLength"]
    except Exception:
        return None


def upload_one(s3, bucket, path: Path, key: str, force: bool):
    try:
        size = path.stat().st_size
        if not force and remote_size(s3, bucket, key) == size:
            return ("skip", key, size, None)
        ctype = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        s3.upload_file(str(path), bucket, key, ExtraArgs={
            "ContentType": ctype,
            "CacheControl": "public, max-age=604800",
        })
        return ("ok", key, size, None)
    except Exception as e:
        return ("fail", key, 0, str(e))


def main(argv):
    load_dotenv()
    catalog_only = "--catalog-only" in argv
    force = "--force" in argv

    if not MATH_DIR.exists():
        print(f"❌ 本地真题目录不存在: {MATH_DIR}")
        return 1

    files = collect_files()
    total_size = sum(f.stat().st_size for f, _ in files)
    print(f"📁 本地共 {len(files)} 个文件，{total_size / 1024 ** 3:.2f} GB")

    if catalog_only:
        write_catalog()
        return 0

    access_key = os.environ.get("CYJY_R2_ACCESS_KEY", "")
    secret_key = os.environ.get("CYJY_R2_SECRET_KEY", "")
    account_id = os.environ.get("CYJY_R2_ACCOUNT_ID", "")
    bucket = os.environ.get("CYJY_R2_BUCKET", "chongyue-math")
    public_url = os.environ.get("CYJY_R2_PUBLIC_URL", "").rstrip("/")
    missing = [n for n, v in (("CYJY_R2_ACCESS_KEY", access_key), ("CYJY_R2_SECRET_KEY", secret_key),
                              ("CYJY_R2_ACCOUNT_ID", account_id)) if not v]
    if missing:
        print("❌ 缺少环境变量: " + ", ".join(missing))
        print("   用法见本文件开头的说明。")
        return 1
    try:
        import boto3  # noqa: F401
    except ImportError:
        print("❌ 请先安装 boto3: pip install boto3")
        return 1

    s3 = get_s3_client(account_id, access_key, secret_key)
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception as e:
        print(f"❌ 无法访问 Bucket '{bucket}': {e}")
        print("   请确认已在 Cloudflare R2 创建该 Bucket，且 API 令牌有读写权限。")
        return 1

    print(f"⬆️  上传到 R2 Bucket '{bucket}'（已存在且大小相同的文件会跳过）…")
    done = skipped = failed = 0
    uploaded = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(upload_one, s3, bucket, f, key, force) for f, key in files]
        for i, fut in enumerate(as_completed(futures), 1):
            status, key, size, err = fut.result()
            if status == "ok":
                done += 1
                uploaded += size
                print(f"   [{i}/{len(files)}] ✅ {key} ({size / 1024 ** 2:.1f} MB)")
            elif status == "skip":
                skipped += 1
            else:
                failed += 1
                print(f"   [{i}/{len(files)}] ❌ {key}: {err}")

    print(f"\n完成：上传 {done} 个（{uploaded / 1024 ** 3:.2f} GB），跳过 {skipped} 个，失败 {failed} 个")
    write_catalog()

    if public_url:
        sample = next((k for _, k in files if k.lower().endswith(".pdf")), None)
        if sample:
            import urllib.request
            import urllib.parse
            try:
                req = urllib.request.Request(f"{public_url}/{urllib.parse.quote(sample)}", method="HEAD")
                code = urllib.request.urlopen(req, timeout=15).status
                print(f"🔎 公网自检 {sample}: HTTP {code}")
            except Exception as e:
                print(f"⚠️  公网自检失败（请确认已开启 Public access）：{e}")

    print("\n📌 下一步：")
    print(f"   1. Render → Environment 添加  CYJY_MATH_FILES_URL = {public_url or '<你的 R2 公网地址，如 https://pub-xxxx.r2.dev>'}")
    print("   2. 提交并推送更新后的 math_catalog.json，Render 会自动重新部署")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
