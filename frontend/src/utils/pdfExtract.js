/**
 * Client-side PDF text extraction using pdf.js.
 *
 * Extracts all text from a PDF file and returns it as a single string.
 * Used to feed user-uploaded papers into Emily's upload_document tool
 * and LACS classification pipeline.
 */

import * as pdfjsLib from "pdfjs-dist";

// Use the bundled worker (avoids CORS issues with CDN)
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

/**
 * Extract text from a PDF File object.
 *
 * @param {File} file  — PDF file from <input type="file">
 * @returns {Promise<{text: string, pages: number, title: string}>}
 */
export async function extractPdfText(file) {
  const buffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: buffer }).promise;
  const pages = pdf.numPages;

  const parts = [];
  for (let i = 1; i <= pages; i++) {
    const page = await pdf.getPage(i);
    const content = await page.getTextContent();
    const pageText = content.items.map((item) => item.str).join(" ");
    parts.push(pageText);
  }

  const text = parts.join("\n\n");
  const title = file.name.replace(/\.pdf$/i, "");

  return { text, pages, title };
}

/**
 * Validate that a file is a PDF and within size limits.
 *
 * @param {File} file
 * @param {number} maxSizeMB  — maximum file size in MB (default 50)
 * @returns {{ok: boolean, error?: string}}
 */
export function validatePdf(file, maxSizeMB = 50) {
  if (!file) return { ok: false, error: "No file selected" };

  const isPdf =
    file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return { ok: false, error: "Only PDF files are supported" };

  const sizeMB = file.size / (1024 * 1024);
  if (sizeMB > maxSizeMB) {
    return { ok: false, error: `File too large (${sizeMB.toFixed(1)}MB, max ${maxSizeMB}MB)` };
  }

  return { ok: true };
}
