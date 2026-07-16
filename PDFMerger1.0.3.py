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

content_frame2 = None
canvas = None


def configure_app_style(root):
    """Apply a modern, flat Slate/Indigo theme using ttk styling."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    # Root background configuration
    root.configure(bg="#f8fafc")

    # Font definitions
    default_font = ("Segoe UI", 10)
    bold_font = ("Segoe UI", 10, "bold")
    header_font = ("Segoe UI", 15, "bold")

    # Frame styles
    style.configure("TFrame", background="#f8fafc")
    style.configure("Card.TFrame", background="#ffffff", relief="flat", borderwidth=0)
    style.configure("White.TFrame", background="#ffffff")
    
    # Label styles
    style.configure("TLabel", background="#f8fafc", foreground="#0f172a", font=default_font)
    style.configure("Card.TLabel", background="#ffffff", foreground="#0f172a", font=default_font)
    style.configure("Header.TLabel", background="#f8fafc", foreground="#0f172a", font=header_font)
    style.configure("Sub.TLabel", background="#f8fafc", foreground="#475569", font=("Segoe UI", 9))
    
    # Button styles
    style.configure("TButton", font=bold_font, padding=(12, 6))
    
    style.configure("Accent.TButton", background="#4f46e5", foreground="white", borderwidth=0)
    style.map("Accent.TButton", background=[("active", "#4338ca"), ("disabled", "#e2e8f0")], foreground=[("disabled", "#94a3b8")])
    
    style.configure("Success.TButton", background="#059669", foreground="white", borderwidth=0)
    style.map("Success.TButton", background=[("active", "#047857"), ("disabled", "#e2e8f0")], foreground=[("disabled", "#94a3b8")])
    
    style.configure("Danger.TButton", background="#dc2626", foreground="white", borderwidth=0)
    style.map("Danger.TButton", background=[("active", "#b91c1c"), ("disabled", "#e2e8f0")], foreground=[("disabled", "#94a3b8")])

    style.configure("Secondary.TButton", background="#e2e8f0", foreground="#0f172a", borderwidth=0)
    style.map("Secondary.TButton", background=[("active", "#cbd5e1"), ("disabled", "#e2e8f0")], foreground=[("disabled", "#94a3b8")])

    # Notebook (Tabs) styling
    style.configure("TNotebook", background="#f8fafc", borderwidth=0)
    style.configure("TNotebook.Tab", background="#e2e8f0", foreground="#475569", padding=(16, 6), font=bold_font, borderwidth=0)
    style.map("TNotebook.Tab", 
              background=[("selected", "#ffffff"), ("active", "#cbd5e1")],
              foreground=[("selected", "#4f46e5")])

    # Entry fields styling
    style.configure("TEntry", fieldbackground="#ffffff", bordercolor="#cbd5e1", lightcolor="#cbd5e1", darkcolor="#cbd5e1", padding=6)


def parse_size_to_bytes(size_text):
    """Parse human-friendly sizes like 10MB, 512KB, 2.5GB into bytes."""
    if size_text is None:
        return None

    text = str(size_text).strip().lower()
    if not text:
        return None

    match = None
    for unit in ("kb", "mb", "gb", "tb", "b"):
        if text.endswith(unit):
            match = unit
            break

    if not match:
        return None

    try:
        value = float(text[:-len(match)].strip())
    except ValueError:
        return None

    multipliers = {"b": 1, "kb": 1024, "mb": 1024 * 1024, "gb": 1024 * 1024 * 1024, "tb": 1024 * 1024 * 1024 * 1024}
    return int(value * multipliers[match])


def estimate_target_dpi_from_size(original_size_bytes, target_size_bytes, min_dpi=72, max_dpi=300, compression_factor=1.0):
    """Estimate a DPI value that should bring the scanned PDF close to the target size.

    The mapping is approximate because real output size depends on image content and JPEG compression.
    A compression_factor greater than 1.0 makes the estimate more aggressive (lower DPI), while a smaller
    value makes it more conservative.
    """
    if not original_size_bytes or not target_size_bytes or original_size_bytes <= 0:
        return max(min_dpi, min(max_dpi, 300))

    ratio = target_size_bytes / float(original_size_bytes)
    ratio = max(0.05, min(1.0, ratio / max(0.2, compression_factor)))
    dpi = int(round(300 * (ratio ** 0.5)))
    return max(min_dpi, min(max_dpi, dpi))


def estimate_compression_factor(original_size_bytes, target_size_bytes, reference_factor=0.65, reference_ratio=0.5):
    """Estimate a compression factor from the source and target size using a reference point.

    The reference case is: a 30MB source reduced to 15MB uses factor 0.65, which means the
    compression factor scales with the ratio target/original relative to the reference ratio 0.5.
    """
    if not original_size_bytes or not target_size_bytes or original_size_bytes <= 0:
        return reference_factor

    current_ratio = target_size_bytes / float(original_size_bytes)
    if current_ratio <= 0:
        return reference_factor

    return max(0.2, min(2.0, reference_factor * (current_ratio / reference_ratio)))


def get_page_ranges(file_listbox, pdf_files, root):
    """Get page ranges for each PDF file"""
    new_pdf_files = [file_listbox.get(i) for i in range(file_listbox.size())]
    pdf_files = list(pdf_files)  # Convert tuple to list
    pdf_files.clear()
    pdf_files.extend(new_pdf_files)

    if not pdf_files:
        messagebox.showwarning("Warning", "No PDF files selected.")
        return

    # Create a loading label in the root frame
    loading_label = ttk.Label(root, text="Đang tải thông tin trang của các file PDF...", style="Sub.TLabel")
    loading_label.pack(pady=10)
    root.update_idletasks()

    def load_pages_and_build_ui():
        try:
            pdf_page_counts = []
            for pdf_file in pdf_files:
                try:
                    reader = PyPDF2.PdfReader(pdf_file)
                    pdf_page_counts.append((pdf_file, len(reader.pages)))
                except Exception:
                    pdf_page_counts.append((pdf_file, 1))

            def build_ui():
                try:
                    loading_label.destroy()
                except Exception:
                    pass

                rb_frame = ttk.Frame(root)
                rb_frame.pack(pady=10, anchor='w', fill='both', expand=True)

                # Create a canvas to hold the content
                canvas = tk.Canvas(rb_frame, width=400, height=300, bg="#f8fafc", highlightthickness=0)
                canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

                # Create a scrollbar and associate it with the canvas
                scrollbar = ttk.Scrollbar(rb_frame, orient=tk.VERTICAL, command=canvas.yview)
                scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                canvas.configure(yscrollcommand=scrollbar.set)

                # Create a frame to hold the content
                content_frame = ttk.Frame(canvas, style="Card.TFrame", padding=16)
                canvas.create_window((0, 0), window=content_frame, anchor='nw')

                entry_fields = []
                for pdf_file, total_pages in pdf_page_counts:
                    # Clean filename for label
                    filename = os.path.basename(pdf_file)
                    file_card = ttk.Frame(content_frame, style="Card.TFrame")
                    file_card.pack(fill='x', pady=6, anchor='w')

                    ttk.Label(file_card, text=filename, font=("Segoe UI", 10, "bold"), foreground="#4f46e5", style="Card.TLabel").pack(anchor='w', pady=(0, 4))
                    
                    row1 = ttk.Frame(file_card, style="White.TFrame")
                    row1.pack(fill='x', pady=2)
                    ttk.Label(row1, text="Start page:", style="Card.TLabel", width=12).pack(side=tk.LEFT)
                    entry_start = ttk.Entry(row1, font=("Segoe UI", 9))
                    entry_start.insert(0, "1")
                    entry_start.pack(side=tk.LEFT, fill='x', expand=True, ipady=2)
                    entry_fields.append(entry_start)

                    row2 = ttk.Frame(file_card, style="White.TFrame")
                    row2.pack(fill='x', pady=2)
                    ttk.Label(row2, text="End page:", style="Card.TLabel", width=12).pack(side=tk.LEFT)
                    entry_end = ttk.Entry(row2, font=("Segoe UI", 9))
                    entry_end.insert(0, str(total_pages))
                    entry_end.pack(side=tk.LEFT, fill='x', expand=True, ipady=2)
                    entry_fields.append(entry_end)

                # Rotation card
                rot_card = ttk.Frame(content_frame, style="Card.TFrame")
                rot_card.pack(fill='x', pady=12, anchor='w')
                ttk.Label(rot_card, text="Góc xoay trái -90, xoay phải +90 (độ):", style="Card.TLabel").pack(anchor='w', pady=(0, 4))
                rotation_entry = ttk.Entry(rot_card, font=("Segoe UI", 9))
                rotation_entry.insert(0, "90")
                rotation_entry.pack(fill='x', ipady=2)

                # Submit button
                submit_btn = ttk.Button(
                    content_frame, 
                    text="Submit Merge", 
                    style="Success.TButton", 
                    command=lambda: submit_page_ranges(entry_fields, pdf_files, rotation_angle=int(rotation_entry.get()))
                )
                submit_btn.pack(pady=12, anchor='c')

                # Update the scroll region
                content_frame.update_idletasks()
                canvas.configure(scrollregion=canvas.bbox("all"))

            root.after(0, build_ui)
        except Exception as err:
            def handle_err():
                try:
                    loading_label.destroy()
                except Exception:
                    pass
                messagebox.showerror("Error", f"Không thể lấy thông tin trang: {err}")
            root.after(0, handle_err)

    threading.Thread(target=load_pages_and_build_ui, daemon=True).start()

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

def merge_pdfs(pdf_files, page_ranges, output_path=None, rotation_angle=0):
    """Merge selected PDF files into a single PDF and return the saved path."""
    if not pdf_files:
        raise ValueError("No PDF files selected")

    if output_path is None:
        output_path = filedialog.asksaveasfilename(
            title="Save merged PDF as",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )

    if not output_path:
        return None

    output_path = os.fspath(output_path)
    output_dir = os.path.dirname(output_path) or os.getcwd()
    os.makedirs(output_dir, exist_ok=True)

    pdf_writer = PyPDF2.PdfWriter()

    for index, pdf_file in enumerate(pdf_files):
        try:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
        except Exception as exc:
            raise ValueError(f"Unable to read PDF file '{pdf_file}': {exc}") from exc

        if index < len(page_ranges):
            page_range = page_ranges[index]
        else:
            page_range = (1, len(pdf_reader.pages))

        start_page, end_page = page_range
        if start_page < 1 or end_page < 1:
            raise ValueError(f"Invalid page range {start_page}-{end_page} for {pdf_file}")

        total_pages = len(pdf_reader.pages)
        if start_page > total_pages or end_page > total_pages:
            raise ValueError(f"Page range {start_page}-{end_page} is out of bounds for {pdf_file}")

        for page_index in range(start_page - 1, end_page):
            page = pdf_reader.pages[page_index]
            if rotation_angle != 0:
                page = page.rotate(rotation_angle)
            pdf_writer.add_page(page)

    with open(output_path, "wb") as pdf_output:
        pdf_writer.write(pdf_output)

    try:
        if os.name == "nt":
            os.startfile(output_path)
    except Exception:
        pass

    return output_path


def process_pdfs(pdf_files, page_ranges, output_path=None, root=None, rotation_angle=0):
    """Process PDFs in a background thread and save the merged output."""
    try:
        if root is not None:
            root.after(0, lambda: messagebox.showinfo("Info", "Processing... Please wait."))

        merged_path = merge_pdfs(pdf_files, page_ranges, output_path=output_path, rotation_angle=rotation_angle )

        if merged_path:
            if root is not None:
                root.after(0, lambda: messagebox.showinfo("Info", f"Processing completed!\nSaved to {merged_path}"))
            else:
                messagebox.showinfo("Info", "Processing completed!")
        else:
            if root is not None:
                root.after(0, lambda: messagebox.showinfo("Info", "Processing cancelled."))
    except Exception as exc:
        if root is not None:
            root.after(0, lambda error=exc: messagebox.showerror("Error", f"Unable to merge PDFs: {error}"))
        else:
            messagebox.showerror("Error", f"Unable to merge PDFs: {exc}")


def submit_page_ranges(entry_fields, pdf_files, rotation_angle):
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

    root = entry_fields[0].winfo_toplevel() if entry_fields else None
    output_path = filedialog.asksaveasfilename(
        parent=root,
        title="Save merged PDF as",
        defaultextension=".pdf",
        filetypes=[("PDF files", "*.pdf")],
    )

    if not output_path:
        return

    processing_thread = threading.Thread(
        target=process_pdfs,
        args=(pdf_files, page_ranges, output_path, root, rotation_angle),
        daemon=True,
    )
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

    doc = None
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
                        return False
                changed = True

        if not changed:
            return False

        doc.save(output_pdf_path, deflate=True)
        return True
    except Exception as e:
        print(f"Không thể nén PDF bằng fitz: {e}")
        return False
    finally:
        if doc is not None:
            doc.close()


def build_pdf_from_jpeg_files(temp_files, output_pdf_path, dpi):
    """Build a PDF from JPEG files using fitz when available, else fallback to img2pdf."""
    if fitz is not None:
        doc = None
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
            return True
        except Exception:
            pass
        finally:
            if doc is not None:
                doc.close()

    if img2pdf is not None:
        with open(output_pdf_path, "wb") as output_file:
            output_file.write(img2pdf.convert(*temp_files, dpi=dpi))
        return True

    pil_images = []
    try:
        pil_images = [Image.open(path) for path in temp_files]
        if pil_images:
            first_image = pil_images[0]
            other_images = pil_images[1:]
            first_image.save(output_pdf_path, "PDF", resolution=dpi, save_all=True, append_images=other_images, quality=20)
        return True
    finally:
        for img in pil_images:
            try:
                img.close()
            except Exception:
                pass


def rasterize_pdf_to_pdf(input_pdf_path, output_pdf_path, target_dpi, quality=None, preserve_color=True, progress_callback=None):
    """Fallback: rasterize each page and rebuild the PDF from compressed JPEG pages."""
    try:
        _report_progress(progress_callback, 0, "Starting optimization")
        #effective_dpi = max(72, min(int(target_dpi), 180))
        effective_dpi = max(72, int(target_dpi))
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
    doc = None
    try:
        doc = fitz.open(pdf_path)
        doc.save(temp_path, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True)
        doc.close()
        doc = None

        if os.path.exists(temp_path) and os.path.getsize(temp_path) < os.path.getsize(pdf_path):
            os.replace(temp_path, pdf_path)
        else:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    except Exception as e:
        print(f"Lỗi khi nén cấu trúc: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
    finally:
        if doc is not None:
            doc.close()


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
        doc = None
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
        finally:
            if doc is not None:
                doc.close()

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
    """Ask user for a PDF file and show inspection results in a background thread."""
    path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
    if not path:
        return

    active_root = tk._default_root or tk.Tk()

    def target():
        stats = inspect_pdf_stats(path)

        def display_result():
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

        active_root.after(0, display_result)

    threading.Thread(target=target, daemon=True).start()


def _report_progress(progress_callback, percent, message=None):
    if progress_callback:
        try:
            progress_callback(max(0, min(100, int(percent))), message)
        except Exception:
            pass


def optimize_pdf_file(input_pdf_path, output_pdf_path, target_dpi, preserve_color=False, progress_callback=None):
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

    suggested = os.path.splitext(os.path.basename(input_path))[0] + "_resized.pdf"
    output_path = filedialog.asksaveasfilename(title="Save resized PDF as", defaultextension='.pdf', initialfile=suggested, filetypes=[("PDF files", "*.pdf")])
    if not output_path:
        return

    original_size = os.path.getsize(input_path) if os.path.exists(input_path) else 0
    target_size_text = simpledialog.askstring(
        "Target size",
        "Enter target size (for example: 15MB, 50MB):",
        initialvalue="15MB",
    )
    if not target_size_text:
        target_size_text = "15MB"

    target_size_bytes = parse_size_to_bytes(target_size_text)
    if target_size_bytes is None or target_size_bytes <= 0:
        messagebox.showerror("Invalid size", "Please enter a valid size such as 15MB or 50MB.")
        return

    estimated_factor = estimate_compression_factor(original_size, target_size_bytes)
    try:
        compression_factor = simpledialog.askfloat(
            "Compression factor",
            f"Optional: adjust the estimate (suggested: {estimated_factor:.2f}; Tăng thêm dung lượng: GIẢM XUỐNG):",
            initialvalue=estimated_factor,
            minvalue=0.2,
            maxvalue=2.0,
        )
    except Exception:
        compression_factor = estimated_factor

    if compression_factor is None:
        compression_factor = estimated_factor

    dpi = estimate_target_dpi_from_size(original_size, target_size_bytes, compression_factor=compression_factor)
    preserve = messagebox.askyesno("Preserve color", "Keep color when compressing?\nChoose No for grayscale output.")

    root = tk._default_root if tk._default_root is not None else tk.Tk()
    progress_window = tk.Toplevel(root)
    progress_window.title("Optimizing PDF")
    progress_window.resizable(False, False)
    progress_window.grab_set()
    progress_window.configure(bg="#f8fafc")

    main_frame = ttk.Frame(progress_window, padding=24)
    main_frame.pack(fill="both", expand=True)

    title_label = ttk.Label(main_frame, text="Optimizing PDF", font=("Segoe UI", 15, "bold"), foreground="#1d4ed8")
    title_label.pack(anchor="w", pady=(0, 6))
    
    sub_label = ttk.Label(main_frame, text=f"Target size: {target_size_text} • Estimated DPI: {dpi} (approximate)", style="Sub.TLabel")
    sub_label.pack(anchor="w", pady=(0, 12))

    progress_var = tk.IntVar(value=0)
    progress_bar = ttk.Progressbar(main_frame, maximum=100, variable=progress_var, length=420, mode="determinate")
    progress_bar.pack(fill="x", pady=(0, 8))
    
    status_label = ttk.Label(main_frame, text="Starting...", style="Sub.TLabel")
    status_label.pack(anchor="w")

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
            messagebox.showinfo("Optimize Complete", f"Method: {method}\nOutput size: {size} bytes")
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
    split_frame = ttk.Frame(parent, padding=24)
    split_frame.pack(fill='both', expand=True)

    # Hero section (clean, modern green alert-like banner)
    hero_frame = tk.Frame(split_frame, bg="#eefbf2", bd=0, highlightthickness=0)
    hero_frame.pack(fill='x', pady=(0, 20))
    title_lbl = tk.Label(hero_frame, text="Tách file PDF", font=("Segoe UI", 16, "bold"), fg="#166534", bg="#eefbf2")
    title_lbl.pack(anchor='w', padx=16, pady=(12, 2))
    desc_lbl = tk.Label(hero_frame, text="Chọn file PDF, nhập phạm vi trang cần giữ và xuất file mới.", font=("Segoe UI", 10), fg="#475569", bg="#eefbf2")
    desc_lbl.pack(anchor='w', padx=16, pady=(0, 12))

    # Main Card container
    card_frame = ttk.Frame(split_frame, style="Card.TFrame", padding=16)
    card_frame.pack(fill='both', expand=True)

    input_var = tk.StringVar()
    output_var = tk.StringVar()
    ranges_var = tk.StringVar(value="1-3,5")
    status_var = tk.StringVar(value="")

    # PDF file input row
    input_row = ttk.Frame(card_frame, style="White.TFrame")
    input_row.pack(fill='x', pady=8)
    ttk.Label(input_row, text="Đường dẫn file PDF:", style="Card.TLabel").pack(anchor='w', pady=(0, 4))
    
    input_entry_frame = ttk.Frame(input_row, style="White.TFrame")
    input_entry_frame.pack(fill='x', expand=True)
    
    input_entry = ttk.Entry(input_entry_frame, textvariable=input_var, font=("Segoe UI", 10))
    input_entry.pack(side=tk.LEFT, fill='x', expand=True, ipady=3)
    
    select_file_btn = ttk.Button(
        input_entry_frame, 
        text="Chọn file", 
        style="Secondary.TButton", 
        width=15,
        command=lambda: input_var.set(filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")]))
    )
    select_file_btn.pack(side=tk.LEFT, padx=(10, 0))

    # Output file input row
    output_row = ttk.Frame(card_frame, style="White.TFrame")
    output_row.pack(fill='x', pady=8)
    ttk.Label(output_row, text="Đường dẫn file xuất:", style="Card.TLabel").pack(anchor='w', pady=(0, 4))
    
    output_entry_frame = ttk.Frame(output_row, style="White.TFrame")
    output_entry_frame.pack(fill='x', expand=True)
    
    output_entry = ttk.Entry(output_entry_frame, textvariable=output_var, font=("Segoe UI", 10))
    output_entry.pack(side=tk.LEFT, fill='x', expand=True, ipady=3)
    
    select_dest_btn = ttk.Button(
        output_entry_frame, 
        text="Chọn nơi lưu", 
        style="Secondary.TButton", 
        width=15,
        command=lambda: output_var.set(filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[("PDF files", "*.pdf")]))
    )
    select_dest_btn.pack(side=tk.LEFT, padx=(10, 0))

    # Page ranges input row
    ranges_row = ttk.Frame(card_frame, style="White.TFrame")
    ranges_row.pack(fill='x', pady=8)
    ttk.Label(ranges_row, text="Phạm vi trang (ví dụ: 1-3,5):", style="Card.TLabel").pack(anchor='w', pady=(0, 4))
    
    ranges_entry = ttk.Entry(ranges_row, textvariable=ranges_var, font=("Segoe UI", 10))
    ranges_entry.pack(fill='x', expand=True, ipady=3)

    # Actions container
    actions_row = ttk.Frame(card_frame, style="White.TFrame")
    actions_row.pack(fill='x', pady=(16, 0))

    def run_split_pdf():
        input_pdf = input_var.get().strip()
        output_pdf = output_var.get().strip()
        if not input_pdf:
            messagebox.showerror("Error", "Vui lòng chọn file PDF trước.")
            return
        if not output_pdf:
            output_pdf = f"{os.path.splitext(input_pdf)[0]}_split.pdf"
        
        status_var.set("Đang tách file PDF...")

        def target():
            try:
                page_ranges = parse_page_ranges_input(ranges_var.get())
                split_pdf_pages(input_pdf, output_pdf, page_ranges)
                
                def on_success():
                    status_var.set(f"Đã tách xong: {output_pdf}")
                    messagebox.showinfo("Info", f"Đã tạo file mới: {output_pdf}")
                    try:
                        os.startfile(output_pdf)
                    except Exception:
                        pass
                
                split_frame.after(0, on_success)
            except Exception as exc:
                def on_failure():
                    status_var.set(f"Lỗi: {exc}")
                    messagebox.showerror("Error", f"Không thể tách file: {exc}")
                
                split_frame.after(0, on_failure)

        threading.Thread(target=target, daemon=True).start()

    split_btn = ttk.Button(actions_row, text="Tách PDF", style="Success.TButton", width=15, command=run_split_pdf)
    split_btn.pack(side=tk.LEFT)
    
    status_label = ttk.Label(actions_row, textvariable=status_var, style="Sub.TLabel")
    status_label.pack(side=tk.LEFT, padx=16)


def build_merge_tab(parent):
    """Create the merge-PDF tab UI."""
    global content_frame2, canvas, main_paned, right_pane_container

    # Create a horizontal Panedwindow inside the merge tab
    main_paned = ttk.Panedwindow(parent, orient=tk.HORIZONTAL)
    main_paned.pack(fill=tk.BOTH, expand=True)

    # Left frame for scrollable action panel
    left_frame = ttk.Frame(main_paned)
    main_paned.add(left_frame, weight=1)

    canvas = tk.Canvas(left_frame, bg="#f8fafc", highlightthickness=0)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    scrollbar = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=canvas.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.configure(yscrollcommand=scrollbar.set)

    content_frame2 = tk.Frame(canvas, bg="#f8fafc")
    canvas.create_window((0, 0), window=content_frame2, anchor='nw')

    # Hero section (modern Slate/Blue alert banner)
    hero_frame = tk.Frame(content_frame2, bg="#eff6ff", bd=0, highlightthickness=0)
    hero_frame.pack(fill='x', padx=24, pady=(24, 16))
    title_lbl = tk.Label(hero_frame, text="PDF Merger", font=("Segoe UI", 20, "bold"), fg="#1d4ed8", bg="#eff6ff")
    title_lbl.pack(anchor='w', padx=16, pady=(12, 2))
    desc_lbl = tk.Label(hero_frame, text="Select PDF files to merge, set page ranges, or compress a scanned PDF to a target size.", font=("Segoe UI", 10), fg="#475569", bg="#eff6ff")
    desc_lbl.pack(anchor='w', padx=16, pady=(0, 12))

    # Main Card container
    card_frame = ttk.Frame(content_frame2, style="Card.TFrame", padding=24)
    card_frame.pack(fill='x', padx=24, pady=12)

    # Right frame container for dynamic content (file list & range selection)
    right_pane_container = ttk.Frame(main_paned)
    main_paned.add(right_pane_container, weight=1)

    # Placeholder card for right pane
    placeholder_card = ttk.Frame(right_pane_container, style="Card.TFrame", padding=32)
    placeholder_card.pack(fill='both', expand=True, pady=40, padx=40)
    
    place_label = ttk.Label(
        placeholder_card, 
        text="No files selected yet\n\nClick 'Select PDF Files' to begin", 
        font=("Segoe UI", 12, "bold"), 
        foreground="#94a3b8", 
        style="Card.TLabel",
        justify="center"
    )
    place_label.pack(expand=True, anchor='c')

    # Actions buttons with standardized style (passing right_pane_container instead of parent)
    select_btn = ttk.Button(card_frame, text="Chọn file để ghép", style="Accent.TButton", width=25, command=lambda: select_pdf_files(right_pane_container))
    select_btn.pack(pady=8, anchor='c')
    
    diag_btn = ttk.Button(card_frame, text="Thông tin file pdf", style="Secondary.TButton", width=25, command=diagnose_pdf_file)
    diag_btn.pack(pady=8, anchor='c')
    
    optimize_btn = ttk.Button(card_frame, text="Resized file pdf", style="Success.TButton", width=25, command=lambda: run_optimize_ui())
    optimize_btn.pack(pady=8, anchor='c')

    reset_button = ttk.Button(card_frame, text="Reset", style="Danger.TButton", width=25, command=lambda: reset_frames(parent.winfo_toplevel()))
    reset_button.pack(pady=8, anchor='c')

    content_frame2.update_idletasks()
    canvas.configure(scrollregion=canvas.bbox("all"))
    canvas.update_idletasks()
    canvas.configure(scrollregion=canvas.bbox("all"))

    try:
        icon_image = Image.open("cooperation_puzzle_icon_262690.ico")
        icon_photo = ImageTk.PhotoImage(icon_image)
        icon_label = tk.Label(content_frame2, image=icon_photo, bg="#f8fafc")
        icon_label.image = icon_photo
        icon_label.pack(pady=16, anchor='c')
    except FileNotFoundError:
        pass

    copyright_frame = tk.Frame(content_frame2, bg="#f8fafc")
    copyright_frame.pack(side=tk.BOTTOM, pady=16, anchor='c')
    copyright_label = tk.Label(copyright_frame, text="© 2026 by Đoàn Lương Bửu", fg="#94a3b8", font=("Segoe UI", 9), bg="#f8fafc")
    copyright_label.pack()


def build_main_ui(root):
    """Create the main notebook with merge and split tabs."""
    configure_app_style(root)
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

    # Clear placeholder or existing frames in the right pane container
    for widget in root.winfo_children():
        widget.destroy()

    # Store the original order of selection
    original_order = list(pdf_files)
    
    # Create a frame to hold the sort button and file list
    rt_frame = ttk.Frame(root, style="Card.TFrame", padding=16)
    rt_frame.pack(pady=12, padx=24, fill='both', expand=True)

    # Create a frame to hold the file list and scrollbar
    file_list_frame = ttk.Frame(rt_frame, style="White.TFrame")
    file_list_frame.pack(anchor='w', fill='both', expand=True, pady=6)

    # Create a scrollbar for the file list
    scrollbar = ttk.Scrollbar(file_list_frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # Create a listbox to display the file list
    file_listbox = tk.Listbox(
        file_list_frame, 
        width=160, 
        height=6, 
        yscrollcommand=scrollbar.set,
        font=("Segoe UI", 9),
        bg="#f8fafc",
        fg="#0f172a",
        selectbackground="#e0e7ff",
        selectforeground="#4f46e5",
        relief="flat",
        highlightthickness=1,
        highlightcolor="#cbd5e1",
        highlightbackground="#cbd5e1"
    )
    file_listbox.pack(side=tk.LEFT, fill='both', expand=True)
    scrollbar.config(command=file_listbox.yview)
    for file in pdf_files:
        file_listbox.insert(tk.END, file)

    # Label & top controls row
    top_row = ttk.Frame(rt_frame, style="White.TFrame")
    top_row.pack(fill='x', before=file_list_frame, pady=(0, 6))

    file_list_label = ttk.Label(top_row, text="Selected Files:", font=("Segoe UI", 10, "bold"), style="Card.TLabel")
    file_list_label.pack(side=tk.LEFT, anchor='w')

    # Create a button to sort the files
    sort_button = ttk.Button(top_row, text="Sort Files A-Z", style="Secondary.TButton", width=15, command=lambda: sort_files(original_order, file_listbox))
    sort_button.pack(side=tk.RIGHT)

    # Create a frame to hold the move up and move down buttons
    button_frame = ttk.Frame(rt_frame, style="White.TFrame")
    button_frame.pack(anchor='w', fill='x', pady=6)

    # Create a button to move the selected file up
    move_up_button = ttk.Button(button_frame, text="Move Up", style="Secondary.TButton", width=15, command=lambda: move_file_up(file_listbox))
    move_up_button.pack(side=tk.LEFT, padx=(0, 6))

    # Create a button to move the selected file down
    move_down_button = ttk.Button(button_frame, text="Move Down", style="Secondary.TButton", width=15, command=lambda: move_file_down(file_listbox))
    move_down_button.pack(side=tk.LEFT)

    # Create a button to proceed to page range selection
    proceed_button = ttk.Button(rt_frame, text="Proceed to Page Range Selection", 
                                 style="Accent.TButton",
                                 width=30,
                                 command=lambda: get_page_ranges(file_listbox, pdf_files, root))
    proceed_button.pack(anchor='c', pady=(12, 0))

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

def sort_files(original_order, file_listbox):
    """Sort the files in alphabetical order"""
    pdf_files = sorted(original_order)
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