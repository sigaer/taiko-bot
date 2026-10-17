const MAX_PARALLEL_PARTS = 3;
const MAX_RETRIES = 3;

const dropZone = document.querySelector('#drop-zone');
const fileInput = document.querySelector('#file-input');
const queueWrap = document.querySelector('#queue-wrap');
const queueElement = document.querySelector('#queue');
const queueSummary = document.querySelector('#queue-summary');
const globalMessage = document.querySelector('#global-message');
const routeProgress = document.querySelector('#route-progress');
const itemTemplate = document.querySelector('#queue-item-template');

const jobs = [];
let processing = false;

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

async function api(path, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error('服务返回了无法识别的响应');
  }
  if (!response.ok || !result.ok) throw new Error(result.message || '请求失败');
  return result;
}

function createJob(file) {
  const fragment = itemTemplate.content.cloneNode(true);
  const element = fragment.querySelector('.queue-item');
  const extension = file.name.includes('.') ? file.name.split('.').pop().slice(0, 4).toUpperCase() : 'FILE';
  element.querySelector('.file-type').textContent = extension;
  element.querySelector('.file-name').textContent = file.name;
  element.querySelector('.file-size').textContent = formatBytes(file.size);
  queueElement.append(element);

  const job = {
    file,
    element,
    state: 'queued',
    progress: 0,
    session: null,
    uploaded: new Map(),
    activeRequests: new Set(),
    paused: false,
    cancelled: false,
  };
  element.querySelector('.file-action').addEventListener('click', () => handleAction(job));
  return job;
}

function addFiles(files) {
  const incoming = [...files].filter((file) => file.size > 0);
  if (!incoming.length) {
    setGlobalMessage('没有可上传的文件，请重新选择。', true);
    return;
  }
  incoming.forEach((file) => jobs.push(createJob(file)));
  fileInput.value = '';
  queueWrap.hidden = false;
  refreshSummary();
  processQueue();
}

function setGlobalMessage(message, isError = false) {
  globalMessage.textContent = message;
  globalMessage.style.color = isError ? 'var(--danger)' : '';
}

function setJobState(job, state, status, action = '') {
  job.state = state;
  const statusElement = job.element.querySelector('.file-status');
  statusElement.textContent = status;
  statusElement.className = `file-status${state === 'error' ? ' is-error' : state === 'success' ? ' is-success' : ''}`;
  const actionButton = job.element.querySelector('.file-action');
  actionButton.textContent = action;
  actionButton.hidden = !action;
  refreshSummary();
}

function updateProgress(job) {
  const uploadedBytes = [...job.uploaded.values()].reduce((sum, item) => sum + item.bytes, 0);
  const activeBytes = [...job.activeRequests].reduce((sum, request) => sum + request.loaded, 0);
  job.progress = Math.min(100, ((uploadedBytes + activeBytes) / job.file.size) * 100);
  job.element.querySelector('.progress-track i').style.width = `${job.progress}%`;
  job.element.querySelector('.file-percent').textContent = `${Math.floor(job.progress)}%`;
  refreshSummary();
}

function refreshSummary() {
  const completed = jobs.filter((job) => job.state === 'success').length;
  const active = jobs.find((job) => ['preparing', 'uploading', 'completing'].includes(job.state));
  queueSummary.textContent = `${completed} / ${jobs.length} 已完成`;
  const totalBytes = jobs.reduce((sum, job) => sum + job.file.size, 0);
  const progressedBytes = jobs.reduce((sum, job) => sum + job.file.size * job.progress / 100, 0);
  routeProgress.style.width = `${totalBytes ? (progressedBytes / totalBytes) * 100 : 0}%`;
  if (active) setGlobalMessage(`正在上传 ${active.file.name}，请保持页面打开。`);
  else if (jobs.length && completed === jobs.length) setGlobalMessage('全部投递完成，可以关闭页面了。');
}

async function handleAction(job) {
  if (job.state === 'queued') {
    job.cancelled = true;
    job.element.remove();
    const index = jobs.indexOf(job);
    if (index >= 0) jobs.splice(index, 1);
    queueWrap.hidden = jobs.length === 0;
    refreshSummary();
  } else if (job.state === 'uploading') {
    job.paused = true;
    job.activeRequests.forEach((request) => request.xhr.abort());
    setJobState(job, 'paused', '已暂停', '继续');
  } else if (job.state === 'paused') {
    job.paused = false;
    setJobState(job, 'uploading', '继续上传中', '暂停');
    uploadParts(job).catch((error) => failJob(job, error));
  } else if (job.state === 'error') {
    job.cancelled = false;
    job.paused = false;
    setJobState(job, 'queued', '等待重试', '移除');
    processQueue();
  }
}

async function processQueue() {
  if (processing) return;
  processing = true;
  while (true) {
    const job = jobs.find((candidate) => candidate.state === 'queued' && !candidate.cancelled);
    if (!job) break;
    try {
      await uploadJob(job);
    } catch (error) {
      failJob(job, error);
    }
  }
  processing = false;
  refreshSummary();
}

async function uploadJob(job) {
  setJobState(job, 'preparing', '正在创建上传任务');
  if (!job.session) {
    job.session = await api('/api/uploads', {
      filename: job.file.name,
      size: job.file.size,
      contentType: job.file.type,
    });
  }
  if (job.session.overwritesExisting) {
    setGlobalMessage(`${job.file.name} 在目标位置已有同名文件，完成后将覆盖旧文件。`);
  }
  setJobState(job, 'uploading', '上传中', '暂停');
  await uploadParts(job);
}

async function uploadParts(job) {
  const pending = [];
  for (let number = 1; number <= job.session.partCount; number += 1) {
    if (!job.uploaded.has(number)) pending.push(number);
  }
  let cursor = 0;

  async function worker() {
    while (cursor < pending.length && !job.paused && !job.cancelled) {
      const number = pending[cursor++];
      const signed = await api('/api/uploads/parts', {
        token: job.session.token,
        partNumbers: [number],
      });
      await uploadPartWithRetry(job, number, signed.urls[number]);
    }
  }

  await Promise.all(Array.from({ length: Math.min(MAX_PARALLEL_PARTS, pending.length) }, worker));
  if (job.paused || job.cancelled) return;
  if (job.uploaded.size !== job.session.partCount) throw new Error('仍有分片未完成');

  setJobState(job, 'completing', '正在合并文件');
  await api('/api/uploads/complete', {
    token: job.session.token,
    parts: [...job.uploaded.entries()].map(([partNumber, value]) => ({ partNumber, etag: value.etag })),
  });
  job.progress = 100;
  updateProgress(job);
  setJobState(job, 'success', '上传完成');
}

async function uploadPartWithRetry(job, number, url) {
  let lastError;
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt += 1) {
    if (job.paused || job.cancelled) return;
    try {
      const etag = await uploadPart(job, number, url);
      const start = (number - 1) * job.session.partSize;
      const end = Math.min(start + job.session.partSize, job.file.size);
      job.uploaded.set(number, { etag, bytes: end - start });
      updateProgress(job);
      return;
    } catch (error) {
      lastError = error;
      if (job.paused || job.cancelled) return;
      if (attempt < MAX_RETRIES) await new Promise((resolve) => setTimeout(resolve, 500 * 2 ** attempt));
    }
  }
  throw lastError;
}

function uploadPart(job, number, url) {
  return new Promise((resolve, reject) => {
    const start = (number - 1) * job.session.partSize;
    const end = Math.min(start + job.session.partSize, job.file.size);
    const requestState = { xhr: new XMLHttpRequest(), loaded: 0 };
    job.activeRequests.add(requestState);
    const finish = () => {
      job.activeRequests.delete(requestState);
      updateProgress(job);
    };
    requestState.xhr.open('PUT', url);
    requestState.xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    requestState.xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) requestState.loaded = event.loaded;
      updateProgress(job);
    });
    requestState.xhr.addEventListener('load', () => {
      const etag = (requestState.xhr.getResponseHeader('ETag') || '').replaceAll('"', '');
      finish();
      if (requestState.xhr.status >= 200 && requestState.xhr.status < 300 && etag) resolve(etag);
      else reject(new Error(`分片 ${number} 上传失败`));
    });
    requestState.xhr.addEventListener('error', () => { finish(); reject(new Error('网络连接中断')); });
    requestState.xhr.addEventListener('abort', () => { finish(); reject(new Error('上传已暂停')); });
    requestState.xhr.send(job.file.slice(start, end, 'application/octet-stream'));
  });
}

function failJob(job, error) {
  if (job.paused || job.cancelled) return;
  console.error(error);
  setJobState(job, 'error', error.message || '上传失败', '重试');
  setGlobalMessage(`${job.file.name} 上传失败：${error.message || '请重试'}`, true);
}

dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    fileInput.click();
  }
});
fileInput.addEventListener('change', () => addFiles(fileInput.files));

for (const eventName of ['dragenter', 'dragover']) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add('is-dragging');
  });
}
for (const eventName of ['dragleave', 'drop']) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove('is-dragging');
  });
}
dropZone.addEventListener('drop', (event) => addFiles(event.dataTransfer.files));
window.addEventListener('beforeunload', (event) => {
  if (jobs.some((job) => ['preparing', 'uploading', 'completing'].includes(job.state))) {
    event.preventDefault();
    event.returnValue = '';
  }
});
