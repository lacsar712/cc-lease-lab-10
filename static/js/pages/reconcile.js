async function 刷新报告() {
  const rows = await 租约台.getJSON('/api/互证');
  const tb = document.getElementById('报告表');
  tb.innerHTML = '';
  for (const r of rows) {
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td>' + 租约台.安全文本(r.报告号) + '</td>' +
      '<td>' + 租约台.安全文本(租约台.格式化时刻(r.时刻)) + '</td>' +
      '<td>' + 租约台.安全文本(r.结论) + '</td>' +
      '<td>' + (r.是否对齐 ? '对齐' : '有差异') + '</td>' +
      '<td>' + 租约台.安全文本(r.差异摘要) + '</td>';
    tb.appendChild(tr);
  }
}

async function 刷新留痕() {
  const rows = await 租约台.getJSON('/api/留痕');
  const tb = document.getElementById('留痕表');
  tb.innerHTML = '';
  for (const r of rows.slice(0, 30)) {
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td>' + 租约台.安全文本(租约台.格式化时刻(r.时刻)) + '</td>' +
      '<td>' + 租约台.安全文本(r.操作) + '</td>' +
      '<td>' + 租约台.安全文本(r.租约号) + '</td>' +
      '<td>' + 租约台.安全文本(r.详情) + '</td>';
    tb.appendChild(tr);
  }
}

document.getElementById('跑互证').onclick = async () => {
  const rep = await 租约台.postJSON('/api/互证/跑', {});
  const 摘要 = {
    结论: rep.结论,
    池已占合计: rep.池已占合计,
    担保现行占用: rep.担保现行占用,
    冻结担保数: rep.冻结担保数,
    待生效租约数: rep.待生效租约数,
    转正担保数: rep.转正担保数,
    生效租约数: rep.生效租约数,
    已退冻影子数: rep.已退冻影子数,
    已取消租约数: rep.已取消租约数,
    差异明细: rep.差异明细,
  };
  document.getElementById('互证详情').textContent = JSON.stringify(摘要, null, 2);
  await 刷新报告();
  await 刷新留痕();
};

刷新报告();
刷新留痕();