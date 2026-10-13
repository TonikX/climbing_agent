"""Offline scan OCR. CSV staging files are not the application's data store.

No network, LLM or database writes. Resume individual pages with --pages.
"""
import argparse
import csv
import hashlib
import io
import subprocess
from pathlib import Path


def write_csv(path, rows, fields):
    temporary = path.with_suffix(path.suffix + ".part")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def main():
    from PIL import Image
    from pypdf import PdfReader

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output/catalog/antalya-2023"))
    parser.add_argument("--pages", help="1-based inclusive range, e.g. 1-114")
    parser.add_argument("--engine", choices=["rapidocr", "windows"], default="rapidocr")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with args.pdf.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    hash_path = args.output / "source.sha256"
    if hash_path.exists() and hash_path.read_text().strip() != digest:
        parser.error("Output directory belongs to a different PDF; choose another --output")
    hash_path.write_text(digest + "\n", encoding="ascii")
    reader = PdfReader(args.pdf)
    start, end = (map(int, args.pages.split("-")) if args.pages else (1, len(reader.pages)))
    if not 1 <= start <= end <= len(reader.pages):
        parser.error("Invalid page range")
    if args.engine == "windows":
        image_dir = args.output / "images"
        image_dir.mkdir(exist_ok=True)
        for number in range(start, end + 1):
            if (args.output / f"page-{number:03d}.csv").exists():
                continue
            for index, embedded in enumerate(reader.pages[number-1].images):
                image = Image.open(io.BytesIO(embedded.data)).convert("RGB")
                panels = 2 if image.width > image.height * 1.15 else 1
                for panel in range(panels):
                    crop = image.crop((image.width*panel//panels,0,image.width*(panel+1)//panels,image.height))
                    crop.thumbnail((2500,2500))
                    crop.save(image_dir / f"{number:03d}-{index}-{panel+1}.jpg", quality=95)
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(Path(__file__).with_name("guidebook_windows_ocr.ps1").resolve()),
                        "-Directory", str(args.output.resolve())], check=True)
        return
    from rapidocr_onnxruntime import RapidOCR
    import cv2
    cv2.setNumThreads(2)
    engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1,
                      det_limit_side_len=1600, det_limit_type="max", use_cls=False,
                      rec_batch_num=16)
    fields = ["page", "image", "panel", "zone", "x", "y", "width", "height", "text", "confidence"]
    for number in range(start, end + 1):
        dest = args.output / f"page-{number:03d}.csv"
        if dest.exists():
            print(f"Page {number}: cached", flush=True)
            continue
        rows = []
        for image_index, embedded in enumerate(reader.pages[number - 1].images):
            image = Image.open(io.BytesIO(embedded.data)).convert("RGB")
            # This scan contains landscape spreads. Keep halves separate so
            # OCR cannot join columns from opposite book pages.
            panels = 2 if image.width > image.height * 1.15 else 1
            for panel in range(panels):
                left, right = image.width * panel // panels, image.width * (panel + 1) // panels
                for zone, top, bottom in [("header", 0, int(image.height * .16)),
                                          ("table", int(image.height * .16), image.height)]:
                    crop = image.crop((left, top, right, bottom))
                    result, _ = engine(crop)
                    for box, text, score in result or []:
                        xs, ys = [p[0] for p in box], [p[1] for p in box]
                        rows.append(dict(page=number, image=image_index, panel=panel + 1, zone=zone,
                                         x=round(min(xs) + left), y=round(min(ys) + top),
                                         width=round(max(xs)-min(xs)), height=round(max(ys)-min(ys)),
                                         text=text, confidence=round(score, 4)))
        write_csv(dest, rows, fields)
        print(f"Page {number}/{len(reader.pages)}: {len(rows)} text boxes", flush=True)


if __name__ == "__main__":
    main()
