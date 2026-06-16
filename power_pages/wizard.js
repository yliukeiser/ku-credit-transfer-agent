/* Upload this file to Power Pages as a Web File with partial URL: /ku-wizard.js */

(function () {
  'use strict';

  const BASE = window.KU_API_BASE || '';
  const KEY  = window.KU_API_KEY  || '';

  if (!BASE) {
    console.error('[KU Wizard] KU_API_BASE is not set. Check the ku/api/base_url site setting.');
  }

  function apiHeaders(isJson) {
    const h = {};
    if (KEY) h['X-API-Key'] = KEY;
    if (isJson) h['Content-Type'] = 'application/json';
    return h;
  }

  let selectedDegreeType = null;
  let selectedProgram    = null;
  let allPrograms        = [];

  // ── helpers ──────────────────────────────────────────────────────────────────

  function goToStep(n) {
    document.querySelectorAll('.step-panel').forEach(p => p.classList.remove('active'));
    document.getElementById(`step-${n}`).classList.add('active');
    for (let i = 1; i <= 5; i++) {
      const tab = document.getElementById(`tab-${i}`);
      tab.classList.remove('active', 'done');
      if (i < n) tab.classList.add('done');
      if (i === n) tab.classList.add('active');
    }
    window.scrollTo(0, 0);
  }

  window.kuRestart = function () {
    selectedDegreeType = null;
    selectedProgram    = null;
    allPrograms        = [];
    document.getElementById('program-search').value = '';
    document.getElementById('transcript-text').value = '';
    document.getElementById('result-content').innerHTML = '';
    document.getElementById('result-btn-row').style.display = 'none';
    document.getElementById('btn-step1').disabled = true;
    document.getElementById('btn-step2').disabled = true;
    loadDegreeTypes();
    goToStep(1);
  };

  // expose step navigation for onclick attributes in the HTML
  window.goToStep  = goToStep;
  window.goToStep2 = goToStep2;
  window.goToStep3 = goToStep3;
  window.goToStep4 = goToStep4;

  // ── Step 1: degree types ──────────────────────────────────────────────────────

  async function loadDegreeTypes() {
    const grid = document.getElementById('degree-grid');
    grid.innerHTML = '<div class="spinner-wrap"><div class="spinner"></div></div>';
    try {
      const res   = await fetch(`${BASE}/api/degree-types`, { headers: apiHeaders(false) });
      const types = await res.json();
      grid.innerHTML = '';
      types.forEach(t => {
        const card = document.createElement('div');
        card.className = 'degree-card';
        card.dataset.type = t.degree_type;
        card.innerHTML = `<div class="badge">${t.short}</div><div class="label">${t.degree_type}</div>`;
        card.onclick = () => selectDegreeType(t.degree_type, card);
        grid.appendChild(card);
      });
    } catch (err) {
      grid.innerHTML = `<p style="color:#b91c1c;padding:16px;font-size:14px">
        Failed to load degree types: ${err.message}<br>
        <a href="javascript:loadDegreeTypes()" style="color:#003087">Click to retry</a>
      </p>`;
    }
  }

  function selectDegreeType(type, card) {
    document.querySelectorAll('.degree-card').forEach(c => c.classList.remove('selected'));
    card.classList.add('selected');
    selectedDegreeType = type;
    document.getElementById('btn-step1').disabled = false;
  }

  async function goToStep2() {
    if (!selectedDegreeType) return;
    goToStep(2);
    document.getElementById('step2-subtitle').textContent =
      `Programs available for: ${selectedDegreeType}`;
    document.getElementById('btn-step2').disabled = true;
    const list = document.getElementById('program-list');
    list.innerHTML = '<div class="spinner-wrap"><div class="spinner"></div></div>';

    const res = await fetch(
      `${BASE}/api/programs?degree_type=${encodeURIComponent(selectedDegreeType)}`,
      { headers: apiHeaders(false) }
    );
    allPrograms = await res.json();
    renderProgramList(allPrograms);
  }

  function renderProgramList(programs) {
    const list = document.getElementById('program-list');
    list.innerHTML = '';
    programs.forEach(p => {
      const item = document.createElement('div');
      item.className = 'program-item' + (selectedProgram && selectedProgram.key === p.key ? ' selected' : '');
      item.innerHTML = `<span class="prog-code">${p.program_code}</span><span class="prog-name">${p.full_name}</span>`;
      item.onclick = () => selectProgram(p, item);
      list.appendChild(item);
    });
    if (programs.length === 0) {
      list.innerHTML = '<p style="padding:20px;color:#9ca3af;text-align:center">No programs found.</p>';
    }
  }

  window.filterPrograms = function () {
    const q = document.getElementById('program-search').value.toLowerCase();
    renderProgramList(allPrograms.filter(p =>
      p.program_name.toLowerCase().includes(q) || p.full_name.toLowerCase().includes(q)
    ));
  };

  function selectProgram(program, item) {
    document.querySelectorAll('.program-item').forEach(i => i.classList.remove('selected'));
    item.classList.add('selected');
    selectedProgram = program;
    document.getElementById('btn-step2').disabled = false;
  }

  // ── Step 3: requirements ──────────────────────────────────────────────────────

  async function goToStep3() {
    if (!selectedProgram) return;
    goToStep(3);
    const wrap = document.getElementById('req-content');
    wrap.innerHTML = '<div class="spinner-wrap"><div class="spinner"></div></div>';

    const res  = await fetch(
      `${BASE}/api/program-requirements?key=${encodeURIComponent(selectedProgram.key)}`,
      { headers: apiHeaders(false) }
    );
    const data = await res.json();
    renderRequirements(data, wrap);
  }

  function renderRequirements(data, wrap) {
    let html = `
      <div class="selected-program-banner">
        <span class="code">${data.program_code}</span>
        <div><div class="name">${data.full_name}</div><div class="type">${data.degree_type}</div></div>
      </div>
      <div class="req-table-wrap">
      <table class="req-table">
        <thead><tr>
          <th style="width:55%">Course / Requirement</th>
          <th style="width:20%">Code</th>
          <th style="width:12%">Credits</th>
        </tr></thead>
        <tbody>`;

    data.categories.forEach(cat => {
      html += `<tr class="row-category">
        <td colspan="2">${cat.name}</td>
        <td><span class="credits-badge">${cat.total_credits} cr</span></td>
      </tr>`;
      cat.disciplines.forEach(disc => {
        const showDisc = disc.name !== cat.name;
        if (showDisc) {
          html += `<tr class="row-discipline">
            <td colspan="2">${disc.name}</td>
            <td><span class="credits-badge">${disc.total_credits} cr</span></td>
          </tr>`;
        }
        disc.courses.forEach(c => {
          html += `<tr class="row-course">
            <td>${c.name}</td>
            <td style="font-family:monospace;font-size:12px">${c.code}</td>
            <td><span class="credits-badge">${c.credits} cr</span></td>
          </tr>`;
        });
      });
    });

    html += `</tbody></table></div>`;
    wrap.innerHTML = html;
  }

  // ── Step 4: PDF upload ────────────────────────────────────────────────────────

  function goToStep4() {
    goToStep(4);
    if (selectedProgram) {
      document.getElementById('step4-program-banner').innerHTML = `
        <div class="selected-program-banner" style="margin-bottom:16px">
          <span class="code">${selectedProgram.program_code}</span>
          <div><div class="name">${selectedProgram.full_name}</div></div>
        </div>`;
    }
  }

  window.onDragOver = function (e) {
    e.preventDefault();
    document.getElementById('upload-zone').classList.add('drag-over');
  };
  window.onDragLeave = function (e) {
    document.getElementById('upload-zone').classList.remove('drag-over');
  };
  window.onDrop = function (e) {
    e.preventDefault();
    document.getElementById('upload-zone').classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) uploadPDF(file);
  };
  window.onFileSelected = function (e) {
    const file = e.target.files[0];
    if (file) uploadPDF(file);
  };

  async function uploadPDF(file) {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      alert('Please upload a PDF file.');
      return;
    }

    const zone = document.getElementById('upload-zone');
    zone.innerHTML = `
      <div class="spinner" style="margin:0 auto 12px"></div>
      <div class="upload-title">Reading PDF…</div>
      <div class="upload-sub">${file.name}</div>`;

    const formData = new FormData();
    formData.append('file', file);

    try {
      // Do NOT set Content-Type here — browser must set it with the multipart boundary.
      const res  = await fetch(`${BASE}/api/extract-pdf`, {
        method: 'POST',
        headers: KEY ? { 'X-API-Key': KEY } : {},
        body: formData,
      });
      const data = await res.json();

      if (data.error) {
        zone.innerHTML = `
          <div class="icon">⚠️</div>
          <div class="upload-title" style="color:#b91c1c">${data.error}</div>
          <div class="upload-sub browse-link" onclick="document.getElementById('pdf-input').click()">Try another file</div>`;
        return;
      }

      zone.style.display = 'none';
      const preview = document.getElementById('extracted-preview');
      preview.style.display = 'block';
      document.getElementById('preview-filename').textContent = `✓ ${file.name}`;
      document.getElementById('transcript-text').value = data.text;
      document.getElementById('btn-evaluate').disabled = false;

    } catch (err) {
      zone.innerHTML = `
        <div class="icon">⚠️</div>
        <div class="upload-title" style="color:#b91c1c">Upload failed. Check that the API service is running.</div>
        <div class="upload-sub browse-link" onclick="document.getElementById('pdf-input').click()">Try again</div>`;
    }
  }

  window.clearUpload = function () {
    document.getElementById('pdf-input').value = '';
    document.getElementById('extracted-preview').style.display = 'none';
    document.getElementById('transcript-text').value = '';
    document.getElementById('btn-evaluate').disabled = true;
    const zone = document.getElementById('upload-zone');
    zone.style.display = 'block';
    zone.innerHTML = `
      <div class="icon">📄</div>
      <div class="upload-title">Drop your transcript PDF here</div>
      <div class="upload-sub">or <span class="browse-link">browse to upload</span></div>
      <div class="upload-sub" style="margin-top:10px">Supports text-based PDF transcripts</div>`;
  };

  // ── Step 5: evaluation ────────────────────────────────────────────────────────

  window.runEvaluation = async function () {
    const text = document.getElementById('transcript-text').value.trim();
    if (!text) { alert('Please paste your transcript text first.'); return; }

    goToStep(5);
    document.getElementById('result-subtitle').textContent =
      `Evaluating transfer credits for: ${selectedProgram.full_name}`;
    document.getElementById('result-content').innerHTML = `
      <div class="spinner-wrap">
        <div class="spinner"></div>
        <p class="spinner-text">Analyzing your transcript against program requirements…<br>This may take 20–40 seconds.</p>
      </div>`;
    document.getElementById('result-btn-row').style.display = 'none';

    try {
      const res = await fetch(`${BASE}/api/evaluate`, {
        method: 'POST',
        headers: apiHeaders(true),
        body: JSON.stringify({ program_key: selectedProgram.key, transcript_text: text }),
      });
      const data = await res.json();
      if (data.error) {
        document.getElementById('result-content').innerHTML =
          `<p style="color:#b91c1c;padding:20px"><strong>Error:</strong> ${data.error}</p>`;
        return;
      }
      if (data.blocked) {
        document.getElementById('result-content').innerHTML = `
          <div style="background:#fee2e2;border:1px solid #fca5a5;border-radius:10px;padding:24px;margin-top:8px">
            <div style="font-size:18px;font-weight:700;color:#b91c1c;margin-bottom:8px">⛔ Credits Not Transferable</div>
            <div style="font-size:14px;color:#7f1d1d">${data.blocked_reason}</div>
            <div style="margin-top:12px;font-size:13px;color:#6b7280">
              School: <strong>${data.school_name}</strong><br>
              ${data.accreditation?.note || ''}
            </div>
          </div>`;
        document.getElementById('result-btn-row').style.display = 'flex';
        return;
      }
      renderResults(data);
      document.getElementById('result-btn-row').style.display = 'flex';
    } catch (err) {
      document.getElementById('result-content').innerHTML =
        `<p style="color:#b91c1c;padding:20px"><strong>Connection error.</strong> Please try again.</p>`;
    }
  };

  function evalTable(headers, rows) {
    if (!rows || rows.length === 0) {
      return `<p style="color:#9ca3af;font-size:13px;margin:8px 0 16px">None found.</p>`;
    }
    let t = `<div style="overflow-x:auto;margin-bottom:4px"><table class="eval-table"><thead><tr>`;
    headers.forEach(h => { t += `<th>${h}</th>`; });
    t += `</tr></thead><tbody>`;
    rows.forEach(r => {
      t += `<tr>`;
      r.forEach((cell, i) => {
        const mono = (i === 0 || i === 3) ? `style="font-family:monospace;font-size:12px"` : '';
        t += `<td ${mono}>${cell ?? ''}</td>`;
      });
      t += `</tr>`;
    });
    t += `</tbody></table></div>`;
    return t;
  }

  function renderResults(d) {
    const strong    = d.strong_matches        || [];
    const potential = d.potential_matches      || [];
    const courses   = d.courses               || [];
    const addl      = d.additional_components || [];
    const notices   = d.summary_notices       || [];
    const accred    = d.accreditation         || {};

    let html = '';

    html += `<div class="result-summary">
      <div class="stat-card">
        <div class="val">${d.total_transfer_credits ?? 0}</div>
        <div class="lbl">Transfer Credits (Strong)</div>
      </div>
      <div class="stat-card">
        <div class="val">${strong.length}</div>
        <div class="lbl">Strong Matches</div>
      </div>
      <div class="stat-card">
        <div class="val">${potential.length}</div>
        <div class="lbl">Potential Matches</div>
      </div>
      <div class="stat-card">
        <div class="val">${courses.length}</div>
        <div class="lbl">Courses on Transcript</div>
      </div>
    </div>`;

    html += `<div class="section-title">1. School Information</div>`;

    const usdebadge = accred.recognized === true
      ? `<span style="background:#dcfce7;color:#15803d;padding:3px 10px;border-radius:99px;font-size:12px;font-weight:700">✓ USDE-Recognized</span>`
      : accred.recognized === false
      ? `<span style="background:#fee2e2;color:#b91c1c;padding:3px 10px;border-radius:99px;font-size:12px;font-weight:700">✗ Not USDE-Recognized</span>`
      : `<span style="background:#fef9c3;color:#a16207;padding:3px 10px;border-radius:99px;font-size:12px;font-weight:700">⚠ Could Not Verify</span>`;

    const accredDisplay = d.accreditation_on_doc
      ? d.accreditation_on_doc
      : (accred.accreditations || []).join(', ') || 'Not mentioned on transcript';

    html += `<table class="eval-table" style="margin-bottom:8px">
      <tbody>
        <tr><td style="width:220px;font-weight:600;color:#374151">School Name</td>
            <td>${d.school_name || '—'}</td></tr>
        <tr><td style="font-weight:600;color:#374151">USDE Recognition</td>
            <td>${usdebadge} &nbsp;<span style="font-size:12px;color:#6b7280">${accred.note || ''}</span></td></tr>
        <tr><td style="font-weight:600;color:#374151">Accreditation Body</td>
            <td style="font-size:13px">${accredDisplay}</td></tr>
        <tr><td style="font-weight:600;color:#374151">FL CCNS Institution</td>
            <td>${d.is_ccns ? '<span style="color:#15803d;font-weight:600">Yes</span>' : 'No'}</td></tr>
        <tr><td style="font-weight:600;color:#374151">Credit System</td>
            <td>${d.credit_system_note || d.credit_system || '—'}</td></tr>
        <tr><td style="font-weight:600;color:#374151">GPA</td>
            <td>${d.gpa != null ? d.gpa : 'Not found on transcript'}</td></tr>
        <tr><td style="font-weight:600;color:#374151">Degree Awarded</td>
            <td>${d.degree_awarded || 'None / Not stated'}</td></tr>
      </tbody>
    </table>`;

    if (d.gen_ed_status && d.gen_ed_status !== 'Not Waived') {
      html += `<div class="waiver-banner">✓ <strong>General Education Waiver — ${d.gen_ed_status}</strong><br><span style="font-weight:400">${d.gen_ed_note || ''}</span></div>`;
    }

    if (notices.length > 0) {
      html += `<div class="section-title">Summary &amp; Notices</div><ul class="action-list" style="margin-bottom:16px">`;
      notices.forEach(n => { html += `<li>${n}</li>`; });
      html += `</ul>`;
    }

    html += `<div class="section-title">2. Courses Taken (Extracted from Transcript)</div>`;
    html += evalTable(
      ['Course Code', 'Course Name', 'Credits (Original)', 'Credits (Semester)', 'Grade'],
      courses.map(c => [c.code, c.name, c.credits_original, c.credits_semester, c.grade])
    );

    if (addl.length > 0) {
      html += `<div class="section-title">Additional Academic Components</div>`;
      html += evalTable(
        ['Type', 'Description', 'Value'],
        addl.map(a => [a.type, a.description, a.value])
      );
    }

    html += `<div class="section-title">3. Strong Matches — Recommended for Transfer</div>`;
    html += evalTable(
      ['KU Course Code', 'KU Course Name', 'KU Credits Req.', 'Transfer Course Code', 'Credits Earned', 'Grade Earned'],
      strong.map(m => [m.ku_code, m.ku_name, m.ku_credits, m.transfer_code, m.transfer_credits, m.transfer_grade])
    );

    html += `<div class="section-title">4. Potential Matches — Advisor Review Required</div>`;
    html += evalTable(
      ['KU Course Code', 'KU Course Name', 'KU Credits Req.', 'Transfer Course Code', 'Credits Earned', 'Grade Earned'],
      potential.map(m => [m.ku_code, m.ku_name, m.ku_credits, m.transfer_code, m.transfer_credits, m.transfer_grade])
    );

    document.getElementById('result-content').innerHTML = html;
  }

  // ── init ──────────────────────────────────────────────────────────────────────
  loadDegreeTypes();

}());
