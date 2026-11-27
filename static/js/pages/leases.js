async function 填池下拉(sel) {
  const rows = await 租约台.getJSON('/api/资源池');
  sel.innerHTML = '';
  for (const r of rows) {
    if (!r.启用) continue;
    const o = document.createElement('option');
    o.value = r.池键;
    o.textContent = r.名称 + ' (' + r.池键 + ')';
    sel.appendChild(o);
  }
}

async function 刷新租约() {
  const st = document.getElementById('状态筛').value;
  const url = st ? '/api/租约?状态=' + encodeURIComponent(st) : '/api/租约';
  const rows = await 租约台.getJSON(url);
  const tb = document.getElementById('租约表');
  tb.innerHTML = '';
  for (const r of rows) {
    const tr = document.createElement('tr');
    let act = '';
    if (r.状态 === '待生效') {
      act =
        '<button class="按钮 琥珀" data-act="激活" data-id="' + 租约台.安全文本(r.租约号) + '">激活</button>' +
        '<button class="按钮 次" data-act="取消" data-id="' + 租约台.安全文本(r.租约号) + '">取消</button>';
    }
    tr.innerHTML =
      '<td>' + 租约台.安全文本(r.租约号) + '</td>' +
      '<td>' + 租约台.安全文本(r.租户) + '</td>' +
      '<td>' + 租约台.安全文本(r.池键) + '</td>' +
      '<td>' + 租约台.状态徽章(r.状态) + '</td>' +
      '<td>' + 租约台.担保徽章(r.担保) + '</td>' +
      '<td>' + 租约台.安全文本(租约台.格式化时刻(r.到期时刻)) + '</td>' +
      '<td class="工具条">' + act + '</td>';
    tb.appendChild(tr);
  }
  tb.querySelectorAll('button').forEach((b) => {
    b.onclick = async () => {
      const msg = document.getElementById('申领消息');
      try {
        if (b.dataset.act === '激活') {
          const row = await 租约台.postJSON('/api/租约/激活', { 租约号: b.dataset.id });
          msg.textContent = '已激活 ' + b.dataset.id + '，担保冻结转正，占用未重复扣减';
        } else {
          const row = await 租约台.postJSON('/api/租约/取消', { 租约号: b.dataset.id });
          msg.textContent = '已取消 ' + b.dataset.id + '，担保已退冻，池名额已回补';
        }
        await 刷新租约();
      } catch (e) {
        msg.textContent = e.message;
      }
    };
  });
}

async function 刷新担保表() {
  const tb = document.getElementById('担保表');
  if (!tb) return;
  const rows = await 租约台.getJSON('/api/担保');
  tb.innerHTML = '';
  for (const g of rows) {
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td>' + 租约台.安全文本(g.指纹) + '</td>' +
      '<td>' + 租约台.安全文本(g.租约号) + '</td>' +
      '<td>' + 租约台.安全文本(g.池键) + '</td>' +
      '<td>' + 租约台.担保徽章({ 担保状态: g.状态 }) + '</td>' +
      '<td>' + 租约台.安全文本(租约台.格式化时刻(g.冻结时)) + '</td>' +
      '<td>' + 租约台.安全文本(租约台.格式化时刻(g.转正时)) + '</td>' +
      '<td>' + 租约台.安全文本(租约台.格式化时刻(g.退冻时)) + '</td>';
    tb.appendChild(tr);
  }
}

async function 刷新全部() {
  await 刷新租约();
  await 刷新担保表();
}

document.getElementById('申领钮').onclick = async () => {
  const msg = document.getElementById('申领消息');
  try {
    const row = await 租约台.postJSON('/api/租约/申领', {
      池键: document.getElementById('申领池').value,
      租户: document.getElementById('申领租户').value,
      租期分钟: Number(document.getElementById('申领分钟').value),
      立即生效: document.getElementById('申领立即').value === '1',
    });
    msg.textContent = row.状态 === '待生效'
      ? '已申领 ' + row.租约号 + ' 待生效，担保已冻结一格池占用'
      : '已申领 ' + row.租约号 + ' ' + row.状态 + '，担保已转正';
    await 刷新租约();
  } catch (e) {
    msg.textContent = e.message;
  }
};

document.getElementById('刷新钮').onclick = () => 刷新全部();
document.getElementById('状态筛').onchange = () => 刷新租约();

填池下拉(document.getElementById('申领池'));
刷新全部();