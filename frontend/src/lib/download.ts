/** Hands the reader a file the page holds (an export) as a download. */
export function saveFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // the click has started the download; the object URL is not needed after it
  setTimeout(() => URL.revokeObjectURL(url), 1_000);
}
