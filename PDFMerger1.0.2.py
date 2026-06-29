from concurrent.futures import ThreadPoolExecutor
import os
import tempfile
import threading
import time
from io import BytesIO
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog
import shutil

import PyPDF2
from PIL import Image, ImageTk
from pdf2image import convert_from_path

try:
    import img2pdf
except ImportError:  # pragma: no cover - optional dependency
    img2pdf = None

try:
    import fitz
except ImportError:
    fitz = None

try:
    import pikepdf
    from pikepdf import ObjectStreamMode
except ImportError:
    pikepdf = None
    ObjectStreamMode = None

#About version
# giảm dpi để giảm dung lượng file
# Bổ sung tính năng slip file

def get_page_ranges(file_listbox, pdf_files, root):
    """Get page ranges for each PDF file"""
    rb_frame = tk.Frame(root)
    rb_frame.pack(pady=10, anchor='w', fill='both', expand=True)

    # Create a canvas to hold the content
    canvas = tk.Canvas(rb_frame, width=400, height=300)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # Create a scrollbar and associate it with the canvas
    scrollbar = tk.Scrollbar(rb_frame, orient=tk.VERTICAL, command=canvas.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.configure(yscrollcommand=scrollbar.set)

    # Create a frame to hold the content
    content_frame = tk.Frame(canvas)
    canvas.create_window((0, 0), window=content_frame, anchor='nw')

    entry_fields = []
    new_pdf_files = [file_listbox.get(i) for i in range(file_listbox.size())]
    pdf_files = list(pdf_files)  # Convert tuple to list
    pdf_files.clear()
    pdf_files.extend(new_pdf_files)

    for pdf_file in pdf_files:
        label = tk.Label(content_frame, text=f"Start page muốn ghép của {pdf_file}:", fg="green")
        label.pack(anchor='w', fill='x')
        entry = tk.Entry(content_frame)
        entry.insert(0, "1")  # Set default value to 1
        entry.pack(anchor='w', fill='x')
        entry_fields.append(entry)

        label = tk.Label(content_frame, text=f"End page muốn ghép của {pdf_file}:", fg="blue")
        label.pack(anchor='w', fill='x')
        entry = tk.Entry(content_frame)
        entry.insert(0, str(len(PyPDF2.PdfReader(pdf_file).pages)))  # Set default value to total number of pages
        entry.pack(anchor='w', fill='x')
        entry_fields.append(entry)

    # Tạo nút Submit
    button = tk.Button(content_frame, text="Submit", command=lambda: submit_page_ranges(entry_fields, pdf_files, dpi_entry))
    button.pack(anchor='c')

    # Update the scroll region
    content_frame.update_idletasks()
    canvas.configure(scrollregion=canvas.bbox("all"))

def parse_page_ranges_input(ranges_text):
    """Parse comma-separated page ranges like '1-3,5' into a list of (start, end)."""
    ranges_text = (ranges_text or "").strip()
    if not ranges_text:
        return []

    parsed_ranges = []
    for part in ranges_text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start_page = int(start_text.strip()) if start_text.strip() else 1
            end_page = int(end_text.strip()) if end_text.strip() else start_page
            if start_page < 1 or end_page < 1 or start_page > end_page:
                raise ValueError(f"Invalid page range '{part}'")
            parsed_ranges.append((start_page, end_page))
        else:
            page_number = int(part)
            if page_number < 1:
                raise ValueError(f"Invalid page number '{part}'")
            parsed_ranges.append((page_number, page_number))
    return parsed_ranges


def process_pdfs(pdf_files, page_ranges):
    """Hàm xử lý PDF trong một luồng riêng"""

    loading_frame = tk.Frame(content_frame2, bg="blue")
    loading_frame.pack(side=tk.BOTTOM, pady=10, padx=20, fill='x')

    loading_label = tk.Label(loading_frame, text="Processing... Please wait.", fg="white", bg="blue", font=("Arial", 16, "bold"))
    loading_label.pack(pady=20)
    content_frame2.update_idletasks()
    canvas.config(scrollregion=canvas.bbox("all"))

    merge_pdfs(pdf_files, page_ranges)

    loading_frame.pack_forget()
    messagebox.showinfo("Info", "Processing completed!")
    
def submit_page_ranges(entry_fields, pdf_files):
    """Submit page ranges and merge PDFs"""
    page_ranges = []

    for i in range(0, len(entry_fields), 2):
        start_page_entry = entry_fields[i]
        end_page_entry = entry_fields[i+1]
        try:
            start_page = int(start_page_entry.get())
            end_page = int(end_page_entry.get())
            if start_page > end_page:
                raise ValueError("Invalid page range")
        except ValueError as e:
            messagebox.showerror("Error", f"Invalid page range: {e}")
            return
        page_ranges.append((start_page, end_page))

    # Tạo một luồng mới để xử lý PDF
    processing_thread = threading.Thread(target=process_pdfs, args=(pdf_files, page_ranges))
    processing_thread.start()


def rasterize_pdf_pages(input_pdf_path, effective_dpi, preserve_color=True):
    """Convert PDF pages to PIL images using pdf2image or fitz."""
    if fitz is not None:
        images = []
        doc = fitz.open(input_pdf_path)
        zoom = effective_dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        for page in doc:
            if preserve_color:
                pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            else:
                pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csGRAY, alpha=False)
                img = Image.frombytes("L", [pix.width, pix.height], pix.samples)
            images.append(img)
        doc.close()
        return images

    return convert_from_path(input_pdf_path, dpi=effective_dpi)


def calculate_image_scale_for_page(image, page, target_dpi):
    """Estimate a downscale factor for an embedded PDF image based on page size."""
    page_width_in = page.rect.width / 72.0
    if page_width_in <= 0:
        return max(0.4, min(1.0, target_dpi / 300.0))

    image_dpi = image.width / page_width_in
    if image_dpi <= 0:
        return 1.0

    scale = min(1.0, target_dpi / image_dpi)
    return max(0.4, scale)


def compress_pdf_images_with_fitz(input_pdf_path, output_pdf_path, target_dpi):
    """Compress embedded images in a PDF using PyMuPDF without rasterizing whole pages."""
    if fitz is None:
        return False

    try:
        doc = fitz.open(input_pdf_path)
        changed = False
        quality = 35 if target_dpi <= 120 else 45

        for page in doc:
            image_list = page.get_images(full=True)
            for image_info in image_list:
                xref = image_info[0]
                image_data = doc.extract_image(xref)
                image_bytes = image_data.get("image")
                if not image_bytes:
                    continue

                img = Image.open(BytesIO(image_bytes))
                img = img.convert("L")
                scale_factor = calculate_image_scale_for_page(img, page, target_dpi)
                if scale_factor < 1.0:
                    new_size = (max(1, int(img.width * scale_factor)), max(1, int(img.height * scale_factor)))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)

                out_buf = BytesIO()
                img.save(out_buf, format="JPEG", quality=quality, optimize=True)
                # PyMuPDF changed replace_image signature across versions.
                # Try page.replace_image first, then fall back to Document.replace_image if available.
                try:
                    page.replace_image(xref, out_buf.getvalue())
                except TypeError:
                    try:
                        # some versions expose replace_image on Document
                        doc.replace_image(xref, out_buf.getvalue())
                    except Exception:
                        # give up on in-place image replacement for this file
                        doc.close()
                        return False
                changed = True

        if not changed:
            doc.close()
            return False

        doc.save(output_pdf_path, deflate=True)
        doc.close()
        return True
    except Exception as e:
        print(f"Không thể nén PDF bằng fitz: {e}")
        return False


def build_pdf_from_jpeg_files(temp_files, output_pdf_path, dpi):
    """Build a PDF from JPEG files using fitz when available, else fallback to img2pdf."""
    if fitz is not None:
        try:
            doc = fitz.open()
            for img_path in temp_files:
                pix = fitz.Pixmap(img_path)
                page_width = pix.width * 72.0 / dpi
                page_height = pix.height * 72.0 / dpi
                page = doc.new_page(width=page_width, height=page_height)
                page.insert_image(fitz.Rect(0, 0, page_width, page_height), filename=img_path)
                pix = None
            doc.save(output_pdf_path, deflate=True, garbage=3)
            doc.close()
            return True
        except Exception:
            pass

    if img2pdf is not None:
        with open(output_pdf_path, "wb") as output_file:
            output_file.write(img2pdf.convert(*temp_files, dpi=dpi))
        return True

    pil_images = [Image.open(path) for path in temp_files]
    first_image = pil_images[0]
    other_images = pil_images[1:]
    first_image.save(output_pdf_path, "PDF", resolution=dpi, save_all=True, append_images=other_images, quality=20)
    return True


def rasterize_pdf_to_pdf(input_pdf_path, output_pdf_path, target_dpi, quality=None, preserve_color=True, progress_callback=None):
    """Fallback: rasterize each page and rebuild the PDF from compressed JPEG pages."""
    try:
        _report_progress(progress_callback, 0, "Starting optimization")
        effective_dpi = max(72, min(int(target_dpi), 180))
        images = rasterize_pdf_pages(input_pdf_path, effective_dpi, preserve_color=preserve_color)
        if not images:
            _report_progress(progress_callback, 100, "No pages found")
            return False

        _report_progress(progress_callback, 10, "Rasterized pages")
        quality = quality if quality is not None else (25 if effective_dpi <= 120 else 30)
        temp_files = []
        try:
            total = len(images)
            for index, image in enumerate(images, start=1):
                processed_image = process_image(image, effective_dpi, quality, preserve_color=preserve_color)
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
                temp_file.write(processed_image)
                temp_file.close()
                temp_files.append(temp_file.name)

                percent = 10 + int(80 * index / total)
                _report_progress(progress_callback, percent, f"Processing page {index}/{total}")

            _report_progress(progress_callback, 95, "Building optimized PDF")
            result = build_pdf_from_jpeg_files(temp_files, output_pdf_path, effective_dpi)
            _report_progress(progress_callback, 100, "Optimization complete")
            return result
        finally:
            for path in temp_files:
                if os.path.exists(path):
                    os.remove(path)

    except Exception as e:
        print(f"Không thể xử lý PDF scan: {str(e)}")
        _report_progress(progress_callback, 100, f"Error: {e}")
        return False


def preprocess_scanned_pdf(input_pdf_path, output_pdf_path, target_dpi):
    """Compress scanned PDF pages by rasterizing if needed for real size reduction."""
    original_size = None
    try:
        original_size = os.path.getsize(input_pdf_path)
    except OSError:
        pass

    if fitz is not None:
        temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        temp_pdf.close()
        try:
            if fitz is not None and compress_pdf_images_with_fitz(input_pdf_path, temp_pdf.name, target_dpi):
                compressed_size = None
                try:
                    compressed_size = os.path.getsize(temp_pdf.name)
                except OSError:
                    pass

                if original_size is not None and compressed_size is not None and compressed_size < original_size:
                    os.replace(temp_pdf.name, output_pdf_path)
                    return True
                os.remove(temp_pdf.name)

            if pikepdf is not None and compress_pdf_with_pikepdf(input_pdf_path, temp_pdf.name):
                compressed_size = None
                try:
                    compressed_size = os.path.getsize(temp_pdf.name)
                except OSError:
                    pass

                if original_size is not None and compressed_size is not None and compressed_size < original_size:
                    os.replace(temp_pdf.name, output_pdf_path)
                    return True
                os.remove(temp_pdf.name)

            if rasterize_pdf_to_pdf(input_pdf_path, output_pdf_path, target_dpi, quality=30):
                if original_size is None:
                    return True
                try:
                    if os.path.getsize(output_pdf_path) < original_size:
                        return True
                    os.remove(output_pdf_path)
                except OSError:
                    pass

            return False
        finally:
            if os.path.exists(temp_pdf.name):
                os.remove(temp_pdf.name)

    if rasterize_pdf_to_pdf(input_pdf_path, output_pdf_path, target_dpi, quality=20):
        return True

    return False


def process_image(image, target_dpi, quality, preserve_color=True):
    """Convert a single page image to a lighter JPEG representation.

    If `preserve_color` is True the image is saved as RGB JPEG, otherwise
    converted to grayscale to reduce size.
    """
    if preserve_color:
        img = image.convert("RGB")
    else:
        img = image.convert("L")

    scale_factor = max(0.4, min(1.0, target_dpi / 300.0))
    width = max(1, int(img.width * scale_factor))
    height = max(1, int(img.height * scale_factor))
    img = img.resize((width, height), Image.Resampling.LANCZOS)

    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format='JPEG', quality=quality, optimize=True)
    img_byte_arr.seek(0)
    return img_byte_arr.getvalue()


def compress_pdf_structure(pdf_path):
    """Use PyMuPDF to garbage-collect and deflate PDF structure for text/vector PDFs."""
    if fitz is None:
        return

    temp_path = f"temp_compress_{os.path.basename(pdf_path)}"
    try:
        doc = fitz.open(pdf_path)
        doc.save(temp_path, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True)
        doc.close()

        if os.path.exists(temp_path) and os.path.getsize(temp_path) < os.path.getsize(pdf_path):
            os.replace(temp_path, pdf_path)
        else:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    except Exception as e:
        print(f"Lỗi khi nén cấu trúc: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)


def compress_pdf_with_pikepdf(input_pdf_path, output_pdf_path):
    """Use pikepdf to recompress PDF object streams and reduce file size."""
    if pikepdf is None:
        return False

    try:
        with pikepdf.Pdf.open(input_pdf_path) as pdf:
            save_kwargs = {
                "compress_streams": True,
                "recompress_flate": True,
                "normalize_content": True,
            }
            if ObjectStreamMode is not None:
                save_kwargs["object_stream_mode"] = ObjectStreamMode.generate

            pdf.save(output_pdf_path, **save_kwargs)

        return True
    except Exception as e:
        print(f"Không thể nén PDF bằng pikepdf: {e}")
        try:
            if os.path.exists(output_pdf_path):
                os.remove(output_pdf_path)
        except OSError:
            pass
        return False


def inspect_pdf_stats(pdf_path):
    """Return basic statistics about a PDF using PyMuPDF (fitz)."""
    # Prefer fitz when available for richer stats
    if fitz is not None:
        try:
            doc = fitz.open(pdf_path)
            pages = doc.page_count
            img_count = 0
            font_names = set()
            text_bytes = 0

            for page in doc:
                try:
                    img_count += len(page.get_images(full=True))
                except Exception:
                    pass

                try:
                    fonts = page.get_fonts()
                    for f in fonts:
                        if len(f) >= 4 and f[3]:
                            font_names.add(f[3])
                except Exception:
                    pass

                try:
                    t = page.get_text("text") or ""
                    text_bytes += len(t.encode("utf8"))
                except Exception:
                    pass

            size = os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0
            doc.close()
            return {
                "pages": pages,
                "images": img_count,
                "fonts": len(font_names),
                "text_bytes": text_bytes,
                "size": size,
                "sample_fonts": list(font_names)[:8],
            }
        except Exception as e:
            return {"error": str(e)}

    # Fallback: try pikepdf to at least get page count and size
    if pikepdf is not None:
        try:
            with pikepdf.Pdf.open(pdf_path) as pdf:
                pages = len(pdf.pages)
            size = os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0
            return {"pages": pages, "images": 0, "fonts": 0, "text_bytes": 0, "size": size}
        except Exception as e:
            return {"error": str(e)}

    # Last fallback: use PyPDF2 to extract basic info (pages, images, fonts)
    try:
        reader = PyPDF2.PdfReader(pdf_path)
        pages = len(reader.pages)
        img_count = 0
        font_names = set()
        text_bytes = 0

        for p in reader.pages:
            try:
                resources = p.get('/Resources') or {}
                xobj = resources.get('/XObject') or {}
                for xo in xobj:
                    try:
                        obj = xobj[xo]
                        subtype = obj.get('/Subtype')
                        if subtype == '/Image':
                            img_count += 1
                    except Exception:
                        pass
            except Exception:
                pass

            try:
                fonts = (p.get('/Resources') or {}).get('/Font') or {}
                for k in fonts:
                    font_names.add(str(k))
            except Exception:
                pass

            try:
                text = p.extract_text() or ""
                text_bytes += len(text.encode('utf8'))
            except Exception:
                pass

        size = os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0
        return {"pages": pages, "images": img_count, "fonts": len(font_names), "text_bytes": text_bytes, "size": size, "sample_fonts": list(font_names)[:8]}
    except Exception as e:
        return {"error": str(e)}


def diagnose_pdf_file():
    """Ask user for a PDF file and show inspection results."""
    path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
    if not path:
        return

    stats = inspect_pdf_stats(path)
    if stats is None:
        messagebox.showerror("Error", "PyMuPDF (fitz) is not available for diagnosis.")
        return

    if "error" in stats:
        messagebox.showerror("Error", f"Cannot inspect PDF:\n{stats['error']}")
        return

    msg = (
        f"File: {os.path.basename(path)}\n"
        f"Pages: {stats['pages']}\n"
        f"Images: {stats['images']}\n"
        f"Fonts: {stats['fonts']}\n"
        f"Text bytes: {stats['text_bytes']}\n"
        f"Size: {stats['size']} bytes\n"
        f"Sample fonts: {', '.join(stats.get('sample_fonts', []))}"
    )
    messagebox.showinfo("PDF Diagnosis", msg)


def _report_progress(progress_callback, percent, message=None):
    if progress_callback:
        try:
            progress_callback(max(0, min(100, int(percent))), message)
        except Exception:
            pass


def optimize_pdf_file(input_pdf_path, output_pdf_path, target_dpi=300, preserve_color=False, progress_callback=None):
    """Optimize a scanned PDF by rasterizing pages at the requested DPI.

    Returns a dict with 'method' and sizes.
    """
    original_size = os.path.getsize(input_pdf_path) if os.path.exists(input_pdf_path) else None

    try:
        ok = rasterize_pdf_to_pdf(
            input_pdf_path,
            output_pdf_path,
            target_dpi,
            quality=None,
            preserve_color=preserve_color,
            progress_callback=progress_callback,
        )

        if not ok:
            if os.path.exists(output_pdf_path):
                try:
                    os.remove(output_pdf_path)
                except Exception:
                    pass
            shutil.copyfile(input_pdf_path, output_pdf_path)
            return {"method": "original", "size": original_size, "original_size": original_size}

        new_size = os.path.getsize(output_pdf_path) if os.path.exists(output_pdf_path) else None
        if original_size is not None and new_size is not None and new_size >= original_size:
            shutil.copyfile(input_pdf_path, output_pdf_path)
            return {"method": "original_kept", "size": original_size, "original_size": original_size}

        return {"method": "rasterize", "size": new_size, "original_size": original_size}
    except Exception as e:
        return {"error": str(e)}


def get_safe_output_path(default_path):
    """Return a writable output path and ask the user to choose another one if needed."""
    if not default_path:
        default_path = "merged_output.pdf"

    directory = os.path.dirname(default_path) or os.getcwd()
    if not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)

    if os.path.exists(default_path):
        try:
            with open(default_path, 'a'):
                pass
            os.remove(default_path)
        except PermissionError:
            messagebox.showerror("Permission denied", f"File is in use or not writable:\n{default_path}")
            return None

    return default_path


def run_optimize_ui():
    """UI helper to run optimize_pdf_file on a chosen file and show results."""
    input_path = filedialog.askopenfilename(title="Select PDF to optimize", filetypes=[("PDF files", "*.pdf")])
    if not input_path:
        return
    suggested = os.path.splitext(os.path.basename(input_path))[0] + "_opt.pdf"
    output_path = filedialog.asksaveasfilename(title="Save optimized PDF as", defaultextension='.pdf', initialfile=suggested, filetypes=[("PDF files", "*.pdf")])
    if not output_path:
        return
    try:
        dpi = simpledialog.askinteger("Target DPI", "Enter target DPI:", initialvalue=300, minvalue=72, maxvalue=600)
    except Exception:
        dpi = 300
    if dpi is None:
        dpi = 300

    preserve = messagebox.askyesno("Preserve color", "Keep color when compressing? (If No, result will be grayscale)")

    root = tk._default_root if tk._default_root is not None else tk.Tk()
    progress_window = tk.Toplevel(root)
    progress_window.title("Optimizing PDF")
    progress_window.resizable(False, False)
    progress_window.grab_set()

    tk.Label(progress_window, text="Optimizing PDF, please wait...").pack(padx=20, pady=(20, 10))
    progress_var = tk.IntVar(value=0)
    progress_bar = ttk.Progressbar(progress_window, maximum=100, variable=progress_var, length=400)
    progress_bar.pack(padx=20, pady=(0, 10))
    status_label = tk.Label(progress_window, text="Starting...")
    status_label.pack(padx=20, pady=(0, 20))

    def update_progress(percent, message=None):
        def apply_update():
            progress_var.set(percent)
            if message:
                status_label.config(text=message)

        try:
            progress_window.after(0, apply_update)
        except Exception:
            pass

    def run_task():
        result = optimize_pdf_file(
            input_path,
            output_path,
            target_dpi=dpi,
            preserve_color=preserve,
            progress_callback=update_progress,
        )

        def finish():
            try:
                progress_window.grab_release()
            except Exception:
                pass
            progress_window.destroy()

            if isinstance(result, dict) and result.get('error'):
                messagebox.showerror("Optimize Error", f"Error: {result['error']}")
                return

            method = result.get('method')
            size = result.get('size')
            messagebox.showinfo("Optimize Complete", f"Method: {method}\nSize: {size}")
            try:
                if os.path.exists(output_path):
                    os.startfile(output_path)
            except Exception:
                pass

        root.after(0, finish)

    worker = threading.Thread(target=run_task, daemon=True)
    worker.start()


def split_pdf_pages(input_pdf_path, output_pdf_path, page_ranges):
    """Extract selected pages from a PDF and save them as a new PDF."""
    reader = PyPDF2.PdfReader(input_pdf_path)
    writer = PyPDF2.PdfWriter()
    total_pages = len(reader.pages)

    if not page_ranges:
        pages_to_extract = list(range(total_pages))
    else:
        pages_to_extract = []
        for start_page, end_page in page_ranges:
            start_page = max(1, min(start_page, total_pages))
            end_page = max(1, min(end_page, total_pages))
            pages_to_extract.extend(range(start_page - 1, end_page))
        pages_to_extract = list(dict.fromkeys(pages_to_extract))

    if not pages_to_extract:
        raise ValueError("No pages selected")

    for page_index in pages_to_extract:
        writer.add_page(reader.pages[page_index])

    output_dir = os.path.dirname(output_pdf_path) or os.getcwd()
    os.makedirs(output_dir, exist_ok=True)

    with open(output_pdf_path, "wb") as output_file:
        writer.write(output_file)

    return True


def build_split_tab(parent):
    """Create the split-PDF tab UI."""
    split_frame = tk.Frame(parent, padx=20, pady=20)
    split_frame.pack(fill='both', expand=True)

    tk.Label(split_frame, text="Tách file PDF", font=("Arial", 16, "bold"), fg="darkgreen").pack(anchor='w', pady=(0, 10))
    tk.Label(split_frame, text="Chọn file PDF, nhập phạm vi trang cần giữ và lưu file mới.", fg="blue").pack(anchor='w', pady=(0, 10))

    input_var = tk.StringVar()
    output_var = tk.StringVar()
    ranges_var = tk.StringVar(value="1-3,5")
    status_var = tk.StringVar(value="")

    input_frame = tk.Frame(split_frame)
    input_frame.pack(fill='x', pady=5)
    tk.Label(input_frame, text="Đường dẫn file PDF:").pack(anchor='w')
    tk.Entry(input_frame, textvariable=input_var, width=110).pack(side=tk.LEFT, fill='x', expand=True)
    tk.Button(input_frame, text="Chọn file", command=lambda: input_var.set(filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")]))).pack(side=tk.LEFT, padx=(10, 0))

    output_frame = tk.Frame(split_frame)
    output_frame.pack(fill='x', pady=5)
    tk.Label(output_frame, text="Đường dẫn file xuất:").pack(anchor='w')
    tk.Entry(output_frame, textvariable=output_var, width=110).pack(side=tk.LEFT, fill='x', expand=True)
    tk.Button(output_frame, text="Chọn nơi lưu", command=lambda: output_var.set(filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[("PDF files", "*.pdf")]))).pack(side=tk.LEFT, padx=(10, 0))

    ranges_frame = tk.Frame(split_frame)
    ranges_frame.pack(fill='x', pady=5)
    tk.Label(ranges_frame, text="Phạm vi trang (ví dụ: 1-3,5):").pack(anchor='w')
    tk.Entry(ranges_frame, textvariable=ranges_var, width=110).pack(fill='x', expand=True)

    def run_split_pdf():
        input_pdf = input_var.get().strip()
        output_pdf = output_var.get().strip()
        if not input_pdf:
            messagebox.showerror("Error", "Vui lòng chọn file PDF trước.")
            return
        if not output_pdf:
            output_pdf = f"{os.path.splitext(input_pdf)[0]}_split.pdf"
        try:
            page_ranges = parse_page_ranges_input(ranges_var.get())
            split_pdf_pages(input_pdf, output_pdf, page_ranges)
            status_var.set(f"Đã tách xong: {output_pdf}")
            messagebox.showinfo("Info", f"Đã tạo file mới: {output_pdf}")
            os.startfile(output_pdf)
        except Exception as exc:
            status_var.set(f"Lỗi: {exc}")
            messagebox.showerror("Error", f"Không thể tách file: {exc}")

    tk.Button(split_frame, text="Tách PDF", command=run_split_pdf, fg="white", bg="darkgreen", font=("Arial", 11, "bold")).pack(anchor='w', pady=(10, 0))
    tk.Label(split_frame, textvariable=status_var, fg="red", wraplength=700, justify='left').pack(anchor='w', pady=(10, 0))


def build_merge_tab(parent):
    """Create the merge-PDF tab UI."""
    global content_frame2, canvas

    canvas = tk.Canvas(parent)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    scrollbar = tk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.configure(yscrollcommand=scrollbar.set)

    content_frame2 = tk.Frame(canvas)
    canvas.create_window((0, 0), window=content_frame2, anchor='nw')

    title_label = tk.Label(content_frame2, text="PDF Merger", font=("Arial", 20, "bold"), fg="red",
                        highlightbackground="blue", highlightcolor="blue")
    title_label.pack(pady=10, anchor='c', fill='x')

    instructions_label = tk.Label(content_frame2, text="Select PDF files to merge and enter the page ranges.", fg="blue",
                                highlightbackground="blue", highlightcolor="blue")
    instructions_label.pack(pady=10, anchor='c', fill='x')

    button = tk.Button(content_frame2, text="Select PDF Files", command=lambda: select_pdf_files(parent))
    button.pack(pady=10, anchor='c')
    diag_btn = tk.Button(content_frame2, text="Diagnose PDF", command=diagnose_pdf_file)
    diag_btn.pack(pady=2, anchor='c')
    optimize_btn = tk.Button(content_frame2, text="Run Optimize", command=lambda: run_optimize_ui())
    optimize_btn.pack(pady=2, anchor='c')

    content_frame2.update_idletasks()
    canvas.configure(scrollregion=canvas.bbox("all"))
    canvas.update_idletasks()
    canvas.configure(scrollregion=canvas.bbox("all"))

    reset_button = tk.Button(content_frame2, text="Reset", fg="white", bg="red", width=5, height=1, font=("Arial", 14, "bold"), padx=10, pady=5, command=lambda: reset_frames(parent.winfo_toplevel()))
    reset_button.pack(pady=10, anchor='c')

    try:
        icon_image = Image.open("cooperation_puzzle_icon_262690.ico")
        icon_photo = ImageTk.PhotoImage(icon_image)
        icon_label = tk.Label(content_frame2, image=icon_photo)
        icon_label.image = icon_photo
        icon_label.pack(pady=10, anchor='c')
    except FileNotFoundError:
        pass

    copyright_frame = tk.Frame(content_frame2)
    copyright_frame.pack(side=tk.BOTTOM, pady=10, anchor='c')
    copyright_label = tk.Label(copyright_frame, text="© 2026 by Đoàn Lương Bửu", fg="gray", font=("Arial", 10))
    copyright_label.pack()


def build_main_ui(root):
    """Create the main notebook with merge and split tabs."""
    notebook = ttk.Notebook(root)
    notebook.pack(fill='both', expand=True, padx=10, pady=10)

    merge_frame = ttk.Frame(notebook)
    notebook.add(merge_frame, text="Merge PDF")
    build_merge_tab(merge_frame)

    split_frame = ttk.Frame(notebook)
    notebook.add(split_frame, text="Split PDF")
    build_split_tab(split_frame)

    return notebook


def select_pdf_files(root):
    """Select PDF files to merge"""
    pdf_files = filedialog.askopenfilenames(title="Select PDF files to merge", 
                                            filetypes=[("PDF files", "*.pdf")])
    if not pdf_files:  # Check if the user has selected any files
        return
    # Store the original order of selection
    original_order = list(pdf_files)
    
    # Create a frame to hold the sort button and file list
    rt_frame = tk.Frame(root)
    rt_frame.pack(pady=10, anchor='w', fill='both', expand=True)

    # Create a button to sort the files
    sort_button = tk.Button(rt_frame, text="Sort Files A-Z", command=lambda: sort_files(original_order, rt_frame))
    sort_button.pack(anchor='w', fill='x')

    # Create a label to display the file list
    file_list_label = tk.Label(rt_frame, text="Selected Files:", highlightcolor='blue')
    file_list_label.pack(anchor='w', fill='x')

    # Create a frame to hold the file list and scrollbar
    file_list_frame = tk.Frame(rt_frame)
    file_list_frame.pack(anchor='w', fill='both', expand=True)

    # Create a scrollbar for the file list
    scrollbar = tk.Scrollbar(file_list_frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # Create a listbox to display the file list
    file_listbox = tk.Listbox(file_list_frame, width=160, height=5, yscrollcommand=scrollbar.set)
    file_listbox.pack(side=tk.LEFT, fill='both', expand=True)
    scrollbar.config(command=file_listbox.yview)
    for file in pdf_files:
        file_listbox.insert(tk.END, file)

    # Create a frame to hold the move up and move down buttons
    button_frame = tk.Frame(rt_frame)
    button_frame.pack(anchor='w', fill='x')

    # Create a button to move the selected file up
    move_up_button = tk.Button(button_frame, text="Move Up", command=lambda: move_file_up(file_listbox))
    move_up_button.pack(side=tk.LEFT)

    # Create a button to move the selected file down
    move_down_button = tk.Button(button_frame, text="Move Down", command=lambda: move_file_down(file_listbox))
    move_down_button.pack(side=tk.LEFT)

    # Create a button to proceed to page range selection
    proceed_button = tk.Button(rt_frame, text="Proceed to Page Range Selection", 
                                command=lambda: get_page_ranges(file_listbox, pdf_files, root))
    proceed_button.pack(anchor='c')

def move_file_up(file_listbox):
    """Move the selected file up in the list"""
    index = file_listbox.curselection()
    if index:
        index = index[0]
        if index > 0:  # Check if the item is not already at the top
            selected_file = file_listbox.get(index)  # Store the selected file
            file_listbox.delete(index)
            file_listbox.insert(index - 1, selected_file)  # Insert the selected file at the new index

def move_file_down(file_listbox):
    """Move the selected file down in the list"""
    index = file_listbox.curselection()
    if index:
        index = index[0]
        if index < file_listbox.size() - 1:  # Check if the item is not already at the bottom
            selected_file = file_listbox.get(index)  # Store the selected file
            file_listbox.delete(index)
            file_listbox.insert(index + 1, selected_file)  # Insert the selected file at the new index

def sort_files(original_order, frame):
    """Sort the files in alphabetical order"""
    pdf_files = sorted(original_order)
    file_listbox = frame.winfo_children()[2]  # Get the listbox widget
    file_listbox.delete(0, tk.END)  # Clear the listbox
    for file in pdf_files:
        file_listbox.insert(tk.END, file)  # Update the listbox with the sorted files

def reset_frames(root):
    for widget in root.winfo_children():
        widget.destroy()
    build_main_ui(root)

if __name__ == '__main__':
    root = tk.Tk()
    root.title("PDF Merger")
    try:
        root.iconbitmap("pdf_filetypes_21618.ico")
    except Exception:
        pass
    root.padding = 10
    root.geometry("1400x700")

    build_main_ui(root)
    root.mainloop()