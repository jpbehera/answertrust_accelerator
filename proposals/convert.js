const { mdToPdf } = require('md-to-pdf');
const path = require('path');
const fs = require('fs');

const dir = __dirname;
const files = fs.readdirSync(dir).filter(f => f.endsWith('.md'));

const css = `
  body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 11pt; line-height: 1.45; color: #1f2328; }
  h1 { font-size: 22pt; border-bottom: 2px solid #0969da; padding-bottom: 6px; }
  h2 { font-size: 15pt; color: #0969da; margin-top: 18px; }
  h3 { font-size: 12pt; }
  code { background: #f6f8fa; padding: 1px 5px; border-radius: 4px; font-size: 9.5pt; }
  pre { background: #f6f8fa; padding: 10px; border-radius: 6px; font-size: 9pt; overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 10pt; }
  th, td { border: 1px solid #d0d7de; padding: 5px 8px; text-align: left; }
  th { background: #f6f8fa; }
  blockquote { border-left: 4px solid #d0d7de; color: #57606a; padding: 0 12px; margin: 10px 0; }
  .mermaid svg { max-width: 100%; height: auto; }
`;

(async () => {
  for (const f of files) {
    const input = path.join(dir, f);
    const output = input.replace(/\.md$/, '.pdf');
    console.log(`Converting ${f} -> ${path.basename(output)}`);
    await mdToPdf(
      { path: input },
      {
        dest: output,
        css,
        marked_extensions: [],
        pdf_options: { format: 'A4', margin: { top: '18mm', bottom: '18mm', left: '16mm', right: '16mm' }, printBackground: true },
        launch_options: { args: ['--no-sandbox'] },
        basedir: dir,
      }
    );
  }
  console.log('Done.');
})().catch(e => { console.error(e); process.exit(1); });
