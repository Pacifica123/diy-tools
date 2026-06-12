import { useEffect, useMemo, useState } from 'react';

const api = window.launcherApi;

const ITEM_TYPES = [
  ['app', 'Программа'],
  ['folder', 'Папка'],
  ['file', 'Файл'],
  ['url', 'Сайт'],
  ['command', 'Команда']
];

function slug(value) {
  const base = String(value || 'item')
    .trim()
    .toLowerCase()
    .replace(/[^a-zа-яё0-9]+/gi, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 34);
  return `${base || 'item'}-${Math.random().toString(36).slice(2, 7)}`;
}

function toPrettyJson(value) {
  return JSON.stringify(value, null, 2);
}

function argsToText(args) {
  if (!args) return '';
  if (Array.isArray(args)) return args.join('\n');
  return String(args);
}

function textToArgs(value) {
  return String(value || '')
    .split('\n')
    .map((x) => x.trim())
    .filter(Boolean);
}

function typeLabel(type) {
  return ITEM_TYPES.find(([id]) => id === type)?.[1] || type || 'Элемент';
}

function defaultItem(profileId) {
  return {
    id: slug(profileId || 'item'),
    name: 'Новая программа',
    type: 'app',
    path: '',
    url: '',
    args: [],
    enabled: true,
    skipIfRunning: true,
    processName: '',
    delayMs: 0
  };
}

function safeItems(profile) {
  return Array.isArray(profile?.items) ? profile.items : [];
}

function StatusPill({ status }) {
  if (!status) return <span className="pill neutral">Не проверено</span>;
  if (status.kind === 'disabled') return <span className="pill neutral">Отключено</span>;
  if (status.ok) return <span className="pill ok">Готово</span>;
  return <span className="pill bad">Проблема</span>;
}

function ProfileModal({ mode, data, onClose, onSave }) {
  const [draft, setDraft] = useState(data);

  function setField(field, value) {
    setDraft((prev) => ({ ...prev, [field]: value }));
  }

  function submit(event) {
    event.preventDefault();
    onSave({
      ...draft,
      id: draft.id || slug(draft.name || 'profile'),
      name: draft.name?.trim() || 'Новый профиль',
      description: draft.description?.trim() || ''
    });
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <form className="modal" onSubmit={submit} onMouseDown={(event) => event.stopPropagation()}>
        <header className="modal-head">
          <div>
            <p className="eyebrow">Профиль</p>
            <h3>{mode === 'create' ? 'Новый профиль' : 'Редактирование профиля'}</h3>
          </div>
          <button type="button" className="icon-button" onClick={onClose}>×</button>
        </header>

        <label>
          Название
          <input value={draft.name || ''} onChange={(event) => setField('name', event.target.value)} autoFocus />
        </label>

        <label>
          Описание
          <input value={draft.description || ''} onChange={(event) => setField('description', event.target.value)} />
        </label>

        <footer className="modal-actions">
          <button type="button" className="ghost" onClick={onClose}>Отмена</button>
          <button type="submit" className="primary">Сохранить</button>
        </footer>
      </form>
    </div>
  );
}

function ItemModal({ mode, data, onClose, onSave }) {
  const [draft, setDraft] = useState({ ...data, argsText: argsToText(data.args) });

  function setField(field, value) {
    setDraft((prev) => ({ ...prev, [field]: value }));
  }

  async function choose(kind) {
    const picked = await api.choosePath(kind);
    if (picked) setField('path', picked);
  }

  function submit(event) {
    event.preventDefault();
    const clean = {
      id: draft.id || slug(draft.name || 'item'),
      name: draft.name?.trim() || 'Без названия',
      type: draft.type || 'app',
      enabled: draft.enabled !== false,
      delayMs: Math.max(0, Number(draft.delayMs) || 0)
    };

    if (clean.type === 'url') {
      clean.url = String(draft.url || '').trim();
    } else {
      clean.path = String(draft.path || '').trim();
    }

    const args = textToArgs(draft.argsText);
    if (args.length) clean.args = args;
    if (draft.processName?.trim()) clean.processName = draft.processName.trim();
    if (draft.skipIfRunning) clean.skipIfRunning = true;

    onSave(clean);
  }

  const isUrl = draft.type === 'url';
  const isPathBased = !isUrl;

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <form className="modal item-modal" onSubmit={submit} onMouseDown={(event) => event.stopPropagation()}>
        <header className="modal-head">
          <div>
            <p className="eyebrow">Элемент запуска</p>
            <h3>{mode === 'create' ? 'Добавить программу' : 'Редактировать программу'}</h3>
          </div>
          <button type="button" className="icon-button" onClick={onClose}>×</button>
        </header>

        <div className="form-grid">
          <label>
            Название
            <input value={draft.name || ''} onChange={(event) => setField('name', event.target.value)} autoFocus />
          </label>

          <label>
            Тип
            <select value={draft.type || 'app'} onChange={(event) => setField('type', event.target.value)}>
              {ITEM_TYPES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
        </div>

        {isUrl ? (
          <label>
            Ссылка
            <input placeholder="https://example.com" value={draft.url || ''} onChange={(event) => setField('url', event.target.value)} />
          </label>
        ) : (
          <label>
            Путь
            <div className="input-row">
              <input placeholder="C:\\Program Files\\..." value={draft.path || ''} onChange={(event) => setField('path', event.target.value)} />
              <button type="button" className="ghost" onClick={() => choose(draft.type === 'folder' ? 'folder' : 'app')}>
                Выбрать
              </button>
            </div>
          </label>
        )}

        {isPathBased && (
          <div className="form-grid">
            <label>
              Аргументы, каждый с новой строки
              <textarea className="mini-area" value={draft.argsText || ''} onChange={(event) => setField('argsText', event.target.value)} />
            </label>
            <label>
              Имя процесса для проверки
              <input placeholder="Discord.exe" value={draft.processName || ''} onChange={(event) => setField('processName', event.target.value)} />
              <span className="field-hint">Нужно для “не запускать повторно”.</span>
            </label>
          </div>
        )}

        <div className="checks">
          <label className="check-line">
            <input type="checkbox" checked={draft.enabled !== false} onChange={(event) => setField('enabled', event.target.checked)} />
            Включить в запуск профиля
          </label>
          {isPathBased && (
            <label className="check-line">
              <input type="checkbox" checked={Boolean(draft.skipIfRunning)} onChange={(event) => setField('skipIfRunning', event.target.checked)} />
              Не запускать повторно, если уже открыто
            </label>
          )}
        </div>

        <label>
          Задержка перед запуском, мс
          <input type="number" min="0" step="250" value={draft.delayMs || 0} onChange={(event) => setField('delayMs', event.target.value)} />
        </label>

        <footer className="modal-actions">
          <button type="button" className="ghost" onClick={onClose}>Отмена</button>
          <button type="submit" className="primary">Сохранить</button>
        </footer>
      </form>
    </div>
  );
}

export default function App() {
  const [profiles, setProfiles] = useState([]);
  const [statuses, setStatuses] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [query, setQuery] = useState('');
  const [log, setLog] = useState([]);
  const [busy, setBusy] = useState(false);
  const [jsonOpen, setJsonOpen] = useState(false);
  const [jsonText, setJsonText] = useState('[]');
  const [modal, setModal] = useState(null);
  const [configPath, setConfigPath] = useState('');

  const selectedProfile = useMemo(
    () => profiles.find((profile) => profile.id === selectedId) || profiles[0],
    [profiles, selectedId]
  );

  const selectedStatus = useMemo(
    () => statuses.find((profile) => profile.id === selectedProfile?.id),
    [statuses, selectedProfile]
  );

  const statusMap = useMemo(() => {
    const map = new Map();
    for (const item of selectedStatus?.items || []) map.set(item.id, item);
    return map;
  }, [selectedStatus]);

  const stats = useMemo(() => {
    const items = safeItems(selectedProfile);
    const enabled = items.filter((item) => item.enabled !== false).length;
    const bad = (selectedStatus?.items || []).filter((item) => !item.ok).length;
    return { total: items.length, enabled, bad };
  }, [selectedProfile, selectedStatus]);

  const filteredItems = useMemo(() => {
    const q = query.trim().toLowerCase();
    const items = safeItems(selectedProfile);
    if (!q) return items;
    return items.filter((item) => {
      const text = `${item.name || ''} ${item.type || ''} ${item.path || ''} ${item.url || ''}`.toLowerCase();
      return text.includes(q);
    });
  }, [query, selectedProfile]);

  function pushLog(message, type = 'info') {
    const time = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    setLog((prev) => [{ time, message, type }, ...prev].slice(0, 90));
  }

  async function refresh(nextSelectedId) {
    try {
      const loaded = await api.getProfiles();
      const checked = await api.validateProfiles();
      const path = await api.getConfigPath();
      setProfiles(loaded);
      setStatuses(checked);
      setJsonText(toPrettyJson(loaded));
      setConfigPath(path);
      if (nextSelectedId) setSelectedId(nextSelectedId);
      else if (!selectedId && loaded[0]) setSelectedId(loaded[0].id);
    } catch (error) {
      pushLog(`Ошибка загрузки: ${error.message}`, 'error');
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function save(nextProfiles, message, nextSelectedId) {
    try {
      const saved = await api.saveProfiles(nextProfiles);
      const checked = await api.validateProfiles();
      setProfiles(saved);
      setStatuses(checked);
      setJsonText(toPrettyJson(saved));
      if (nextSelectedId) setSelectedId(nextSelectedId);
      else if (!saved.find((profile) => profile.id === selectedId) && saved[0]) setSelectedId(saved[0].id);
      if (message) pushLog(message, 'success');
    } catch (error) {
      pushLog(`Не сохранено: ${error.message}`, 'error');
    }
  }

  async function launchProfile(profile) {
    if (!profile) return;
    setBusy(true);
    pushLog(`Запускаю профиль: ${profile.name}`, 'info');
    try {
      const results = await api.launchProfile(profile.id);
      for (const result of results) {
        if (result.skipped && result.reason === 'disabled') pushLog(`Пропуск: ${result.name} отключён`, 'muted');
        else if (result.skipped) pushLog(`Пропуск: ${result.name} уже запущен`, 'muted');
        else if (result.ok) pushLog(`ОК: ${result.name}`, 'success');
        else pushLog(`Ошибка: ${result.name} — ${result.error}`, 'error');
      }
      await refresh(profile.id);
    } catch (error) {
      pushLog(`Ошибка профиля: ${error.message}`, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function launchItem(profile, item) {
    setBusy(true);
    try {
      const result = await api.launchItem(profile.id, item.id);
      if (result.skipped) pushLog(`Пропуск: ${item.name} уже запущен`, 'muted');
      else pushLog(`ОК: ${item.name}`, 'success');
    } catch (error) {
      pushLog(`Ошибка: ${item.name} — ${error.message}`, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function revealItem(profile, item) {
    try {
      await api.revealItem(profile.id, item.id);
    } catch (error) {
      pushLog(`Не удалось открыть расположение: ${error.message}`, 'error');
    }
  }

  function openCreateProfile() {
    setModal({ kind: 'profile', mode: 'create', data: { id: slug('profile'), name: 'Новый профиль', description: '', items: [] } });
  }

  function saveProfile(profileDraft) {
    const next = modal.mode === 'create'
      ? [...profiles, { ...profileDraft, items: [] }]
      : profiles.map((profile) => profile.id === profileDraft.id ? { ...profile, ...profileDraft } : profile);
    save(next, 'Профиль сохранён', profileDraft.id);
    setModal(null);
  }

  function deleteProfile(profile) {
    if (!profile) return;
    const ok = window.confirm(`Удалить профиль “${profile.name}”?`);
    if (!ok) return;
    const next = profiles.filter((p) => p.id !== profile.id);
    save(next, 'Профиль удалён', next[0]?.id || '');
  }

  function saveItem(itemDraft) {
    const profileId = selectedProfile.id;
    const next = profiles.map((profile) => {
      if (profile.id !== profileId) return profile;
      const items = safeItems(profile);
      const nextItems = modal.mode === 'create'
        ? [...items, itemDraft]
        : items.map((item) => item.id === itemDraft.id ? itemDraft : item);
      return { ...profile, items: nextItems };
    });
    save(next, 'Элемент сохранён', profileId);
    setModal(null);
  }

  function toggleItem(item) {
    const next = profiles.map((profile) => {
      if (profile.id !== selectedProfile.id) return profile;
      return {
        ...profile,
        items: safeItems(profile).map((x) => x.id === item.id ? { ...x, enabled: x.enabled === false } : x)
      };
    });
    save(next, item.enabled === false ? 'Элемент включён' : 'Элемент отключён', selectedProfile.id);
  }

  function deleteItem(item) {
    const ok = window.confirm(`Удалить “${item.name}”?`);
    if (!ok) return;
    const next = profiles.map((profile) => profile.id === selectedProfile.id
      ? { ...profile, items: safeItems(profile).filter((x) => x.id !== item.id) }
      : profile);
    save(next, 'Элемент удалён', selectedProfile.id);
  }

  function duplicateItem(item) {
    const copy = { ...item, id: slug(item.name), name: `${item.name} — копия` };
    const next = profiles.map((profile) => profile.id === selectedProfile.id
      ? { ...profile, items: [...safeItems(profile), copy] }
      : profile);
    save(next, 'Элемент скопирован', selectedProfile.id);
  }

  function moveItem(item, direction) {
    const next = profiles.map((profile) => {
      if (profile.id !== selectedProfile.id) return profile;
      const items = [...safeItems(profile)];
      const index = items.findIndex((x) => x.id === item.id);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= items.length) return profile;
      [items[index], items[target]] = [items[target], items[index]];
      return { ...profile, items };
    });
    save(next, 'Порядок обновлён', selectedProfile.id);
  }

  async function saveJson() {
    try {
      const parsed = JSON.parse(jsonText);
      if (!Array.isArray(parsed)) throw new Error('В редакторе должен быть массив profiles, без внешнего объекта');
      await save(parsed, 'JSON сохранён', selectedProfile?.id);
    } catch (error) {
      pushLog(`JSON не сохранён: ${error.message}`, 'error');
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">▶</div>
          <div>
            <h1>App Launcher</h1>
            <p>Запуск наборов программ</p>
          </div>
        </div>

        <button className="primary wide" disabled={!selectedProfile || busy} onClick={() => launchProfile(selectedProfile)}>
          Запустить выбранный
        </button>

        <nav className="profile-list">
          {profiles.map((profile) => {
            const count = safeItems(profile).length;
            const active = profile.id === selectedProfile?.id;
            return (
              <button key={profile.id} className={active ? 'profile active' : 'profile'} onClick={() => setSelectedId(profile.id)}>
                <span>{profile.name}</span>
                <small>{count} элементов</small>
              </button>
            );
          })}
        </nav>

        <div className="side-actions">
          <button className="ghost" onClick={openCreateProfile}>+ Профиль</button>
          <button className="ghost" onClick={() => refresh(selectedProfile?.id)}>Обновить</button>
          <button className="ghost" onClick={() => api.revealConfig()}>Открыть конфиг</button>
        </div>
      </aside>

      <section className="content">
        <header className="hero">
          <div className="hero-text">
            <p className="eyebrow">Выбранный профиль</p>
            <h2>{selectedProfile?.name || 'Профилей пока нет'}</h2>
            <p>{selectedProfile?.description || 'Создай профиль и добавь программы через кнопку “Добавить”.'}</p>
          </div>
          <div className="hero-actions">
            <button className="ghost" disabled={!selectedProfile} onClick={() => setModal({ kind: 'profile', mode: 'edit', data: selectedProfile })}>
              Настроить профиль
            </button>
            <button className="primary" disabled={!selectedProfile || busy} onClick={() => launchProfile(selectedProfile)}>
              Запустить всё
            </button>
          </div>
        </header>

        <section className="summary-grid">
          <article className="summary-card">
            <strong>{stats.total}</strong>
            <span>Всего элементов</span>
          </article>
          <article className="summary-card">
            <strong>{stats.enabled}</strong>
            <span>Включено</span>
          </article>
          <article className={stats.bad ? 'summary-card warn' : 'summary-card'}>
            <strong>{stats.bad}</strong>
            <span>Проблем с путями</span>
          </article>
          <article className="summary-card path-card" title={configPath}>
            <strong>apps.json</strong>
            <span>{configPath || 'Конфиг ещё не загружен'}</span>
          </article>
        </section>

        <section className="toolbar">
          <div className="search-box">
            <span>⌕</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Быстрый поиск по программам" />
          </div>
          <button disabled={!selectedProfile} onClick={() => setModal({ kind: 'item', mode: 'create', data: defaultItem(selectedProfile?.id) })}>
            + Добавить
          </button>
          <button className="ghost danger" disabled={!selectedProfile} onClick={() => deleteProfile(selectedProfile)}>
            Удалить профиль
          </button>
        </section>

        <section className="cards">
          {filteredItems.length === 0 ? (
            <div className="empty-state">
              <h3>Здесь пока пусто</h3>
              <p>Добавь программу, папку или сайт. Потом весь профиль будет запускаться одной кнопкой.</p>
            </div>
          ) : filteredItems.map((item) => {
            const status = statusMap.get(item.id);
            const target = item.type === 'url' ? item.url : item.path;
            return (
              <article className={item.enabled === false ? 'card disabled-card' : 'card'} key={item.id}>
                <div className="card-top">
                  <div>
                    <div className="type-row">
                      <span className="type-badge">{typeLabel(item.type)}</span>
                      <StatusPill status={status} />
                    </div>
                    <h3>{item.name}</h3>
                  </div>
                  <label className="switch" title="Включить в запуск профиля">
                    <input type="checkbox" checked={item.enabled !== false} onChange={() => toggleItem(item)} />
                    <span />
                  </label>
                </div>

                <code title={target}>{target || 'Путь или URL не указан'}</code>
                {status?.issue && <p className="issue">{status.issue}</p>}
                {item.args?.length > 0 && <p className="muted small-text">Аргументы: {item.args.join(' ')}</p>}

                <div className="card-actions">
                  <button disabled={busy || item.enabled === false} onClick={() => launchItem(selectedProfile, item)}>Запустить</button>
                  <button className="ghost" onClick={() => revealItem(selectedProfile, item)}>Открыть</button>
                  <button className="ghost" onClick={() => setModal({ kind: 'item', mode: 'edit', data: item })}>Править</button>
                </div>

                <div className="mini-actions">
                  <button className="text-button" onClick={() => moveItem(item, -1)}>↑ выше</button>
                  <button className="text-button" onClick={() => moveItem(item, 1)}>↓ ниже</button>
                  <button className="text-button" onClick={() => duplicateItem(item)}>копия</button>
                  <button className="text-button danger-text" onClick={() => deleteItem(item)}>удалить</button>
                </div>
              </article>
            );
          })}
        </section>

        <section className="lower-grid">
          <section className="panel">
            <div className="panel-title">
              <h3>Журнал запуска</h3>
              <button className="ghost small" onClick={() => setLog([])}>Очистить</button>
            </div>
            <div className="log-list">
              {log.length === 0 ? (
                <p className="muted">Пока ничего не запускалось.</p>
              ) : log.map((entry, index) => (
                <div className={`log ${entry.type}`} key={`${entry.time}-${index}`}>
                  <span>{entry.time}</span>
                  <p>{entry.message}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="panel help-panel">
            <div className="panel-title">
              <h3>Удобные фишки</h3>
              <button className="ghost small" onClick={() => setJsonOpen((value) => !value)}>
                {jsonOpen ? 'Скрыть JSON' : 'JSON'}
              </button>
            </div>
            <ul className="tips">
              <li>Отключай редкие программы тумблером — они останутся в профиле.</li>
              <li>Кнопка “Выбрать” сама подставляет путь к `.exe` или папке.</li>
              <li>“Не запускать повторно” помогает не плодить Discord, Steam и лаунчеры.</li>
            </ul>
            {jsonOpen && (
              <div className="json-editor">
                <textarea value={jsonText} onChange={(event) => setJsonText(event.target.value)} />
                <button className="primary wide" onClick={saveJson}>Сохранить JSON</button>
              </div>
            )}
          </section>
        </section>
      </section>

      {modal?.kind === 'profile' && (
        <ProfileModal mode={modal.mode} data={modal.data} onClose={() => setModal(null)} onSave={saveProfile} />
      )}
      {modal?.kind === 'item' && (
        <ItemModal mode={modal.mode} data={modal.data} onClose={() => setModal(null)} onSave={saveItem} />
      )}
    </main>
  );
}
