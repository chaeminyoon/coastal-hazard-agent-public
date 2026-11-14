export function downloadInBrowser(url: string, filename?: string) {
  const link = document.createElement("a");
  link.href = url;
  if (filename) link.download = filename;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
}
