import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

function download(report, format) {
  const lines = ['Website Audit Report', report.generated_at, report.final_url];
  for (const [name, section] of Object.entries(report.sections)) {
    lines.push('', name + ' — ' + section.score + '/100');
    for (const check of section.checks) {
      lines.push((check.passed ? 'PASS' : 'REVIEW') + ' — ' + check.label,
        'Evidence: ' + check.evidence);
      if (!check.passed) lines.push('Action: ' + check.action);
    }
  }
  lines.push('', 'Grok: ' + report.ai_status, report.ai_notes);
  const json = format === 'json';
  const file = new Blob([json ? JSON.stringify(report, null, 2) : lines.join('\n')],
    { type: json ? 'application/json' : 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'website-audit.' + format;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function App() {
  const [url, setUrl] = useState('');
  const [report, setReport] = useState(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  async function audit(event) {
    event.preventDefault();
    setPending(true);
    setReport(null);
    setError('');
    try {
      const response = await fetch('/api/audit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim() }),
        signal: AbortSignal.timeout(55000),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(typeof result.detail === 'string' ? result.detail : 'Check the website URL and try again.');
      }
      setReport(result);
    } catch (err) {
      setError(err instanceof SyntaxError || err instanceof TypeError
        ? 'Could not reach the audit service. Check that the backend is running.' : err.message);
    } finally {
      setPending(false);
    }
  }

  return <main>
    <header>
      <p className="eyebrow">SINGLE-PAGE AUDIT</p>
      <h1>AI Website Audit Assistant</h1>
      <p>Review search engine optimization (SEO) and answer engine optimization (AEO) signals for a public web page.</p>
    </header>
    <form onSubmit={audit}>
      <label htmlFor="url">Website URL</label>
      <div className="row">
        <input id="url" type="url" required maxLength={2048} placeholder="https://www.iana.org"
          value={url} onChange={event => setUrl(event.target.value)} />
        <button disabled={pending}>Run audit</button>
      </div>
      {pending && <p role="status">Fetching and auditing the page…</p>}
      {error && <p role="alert">{error}</p>}
    </form>
    {report && <article>
      <div className="row actions">
        <button onClick={() => download(report, 'txt')}>Download text report</button>
        <button onClick={() => download(report, 'json')}>Download JSON</button>
        <button onClick={() => window.print()}>Print / save PDF</button>
      </div>
      <p className="target">Audited page: {report.final_url}</p>
      <p>Scores reflect the share of checks passed.</p>
      <div className="results">
        {Object.entries(report.sections).map(([name, section]) => <section key={name}>
          <h2>{name} <span>{section.score}/100</span></h2>
          <ul>{section.checks.map(check => <li key={check.label}>
            <strong>{check.passed ? 'Pass' : 'Review'} · {check.label}</strong>
            <p>{check.evidence}</p>
            {!check.passed && <p>{check.action}</p>}
          </li>)}</ul>
        </section>)}
      </div>
      <section>
        <h2>Grok recommendations</h2>
        <p className="notes">{report.ai_status === 'complete' ? report.ai_notes :
          report.ai_status === 'disabled' ? 'Set XAI_API_KEY to enable Grok recommendations.' :
            'Grok recommendations were unavailable for this audit.'}</p>
      </section>
    </article>}
  </main>;
}

createRoot(document.getElementById('root')).render(<App />);
