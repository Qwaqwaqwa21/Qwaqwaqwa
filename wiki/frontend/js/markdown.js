// Minimal, dependency-free Markdown -> HTML renderer.
// Supports: headers, bold/italic, inline code, code fences, tables,
// unordered/ordered lists, links, blockquotes, paragraphs.
// Kept intentionally small — no CDN fetch, so the wiki works fully offline.
function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderInline(text) {
  let out = escapeHtml(text);
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return out;
}

function renderMarkdown(md) {
  const lines = (md || "").replace(/\r\n/g, "\n").split("\n");
  let html = "";
  let i = 0;
  let inList = null; // 'ul' | 'ol'

  function closeList() {
    if (inList) { html += `</${inList}>`; inList = null; }
  }

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim().startsWith("```")) {
      closeList();
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      html += `<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`;
      i++;
      continue;
    }

    const headerMatch = line.match(/^(#{1,4})\s+(.*)$/);
    if (headerMatch) {
      closeList();
      const level = headerMatch[1].length;
      html += `<h${level}>${renderInline(headerMatch[2])}</h${level}>`;
      i++;
      continue;
    }

    if (line.trim().startsWith("|") && lines[i + 1] && /^\s*\|?\s*-{2,}/.test(lines[i + 1])) {
      closeList();
      const headerCells = line.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        rows.push(lines[i].trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim()));
        i++;
      }
      html += "<table><thead><tr>" + headerCells.map(c => `<th>${renderInline(c)}</th>`).join("") + "</tr></thead><tbody>";
      for (const r of rows) {
        html += "<tr>" + r.map(c => `<td>${renderInline(c)}</td>`).join("") + "</tr>";
      }
      html += "</tbody></table>";
      continue;
    }

    const ulMatch = line.match(/^\s*[-*]\s+(.*)$/);
    const olMatch = line.match(/^\s*\d+\.\s+(.*)$/);
    if (ulMatch || olMatch) {
      const tag = ulMatch ? "ul" : "ol";
      if (inList !== tag) { closeList(); html += `<${tag}>`; inList = tag; }
      let itemText = renderInline((ulMatch || olMatch)[1]);
      let j = i + 1;
      while (
        j < lines.length &&
        /^\s+\S/.test(lines[j]) &&
        !/^\s*[-*]\s+/.test(lines[j]) &&
        !/^\s*\d+\.\s+/.test(lines[j])
      ) {
        itemText += " " + renderInline(lines[j].trim());
        j++;
      }
      html += `<li>${itemText}</li>`;
      i = j;
      continue;
    }

    if (line.trim().startsWith(">")) {
      closeList();
      html += `<blockquote>${renderInline(line.trim().replace(/^>\s?/, ""))}</blockquote>`;
      i++;
      continue;
    }

    if (line.trim() === "") {
      closeList();
      i++;
      continue;
    }

    closeList();
    html += `<p>${renderInline(line.trim())}</p>`;
    i++;
  }
  closeList();
  return html;
}
