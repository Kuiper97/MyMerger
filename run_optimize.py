import json
import importlib.util
import sys
import os

module_path = os.path.join(os.path.dirname(__file__), 'PDFMerger1.0.2.py')
spec = importlib.util.spec_from_file_location('pdfmerger_mod', module_path)
pdfmod = importlib.util.module_from_spec(spec)
sys.modules['pdfmerger_mod'] = pdfmod
spec.loader.exec_module(pdfmod)

infile = 'CV1778.pdf'
outfile = 'CV1778_optimized.pdf'
res = pdfmod.optimize_pdf_file(infile, outfile, target_dpi=150, preserve_color=True)
print(json.dumps(res, indent=2))
print('outfile exists', os.path.exists(outfile), 'size', os.path.getsize(outfile) if os.path.exists(outfile) else None)
