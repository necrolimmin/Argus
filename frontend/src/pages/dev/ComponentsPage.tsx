import { KeyRound, Pencil, Plus, Radar, RefreshCw, Router, Search, Trash2, VideoOff } from "lucide-react";
import { useState } from "react";

import type { OrgUnit } from "../../api/types";
import { DirectionBadge } from "../../components/DirectionBadge";
import { OrgTree } from "../../components/OrgTree";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import "./components.css";

/*
 * Every shared component in every state, for checking the design system in
 * the real app. Development builds only: App.tsx mounts it behind
 * import.meta.env.DEV, so production never ships it.
 */

const UNITS: OrgUnit[] = [
  { id: "c1", parent_id: null, level: "company", name: "Головной офис", camera_count: 9, employee_count: 42 },
  { id: "b1", parent_id: "c1", level: "branch", name: "Проходная", camera_count: 7, employee_count: 0 },
  { id: "b2", parent_id: "c1", level: "branch", name: "Склад", camera_count: 2, employee_count: 6 },
  { id: "e1", parent_id: "b1", level: "enterprise", name: "Xodimlar va muassasalar", camera_count: 3, employee_count: 11 },
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="card dev-section">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

export function ComponentsPage() {
  const [unit, setUnit] = useState<string | null>("b1");
  const [seg, setSeg] = useState("all");
  return (
    <div className="page dev-page">
      <div className="page-head">
        <h1>Компоненты</h1>
        <span className="muted">только в dev-сборке</span>
      </div>

      <Section title="Кнопки: четыре уровня">
        <div className="row wrap">
          <button className="btn btn-primary">
            <Plus size={16} />
            Добавить
          </button>
          <button className="btn">
            <Radar size={16} />
            Сканировать сеть
          </button>
          <button className="btn btn-ghost">
            <KeyRound size={16} />
            Учётные данные
          </button>
          <button className="btn btn-danger">
            <Trash2 size={16} />
            Удалить
          </button>
          <button className="btn btn-danger solid">Удалить устройство</button>
        </div>
        <div className="row wrap mt-3">
          <button className="btn btn-primary" disabled>
            Добавить
          </button>
          <button className="btn" disabled>
            Сканировать сеть
          </button>
          <button className="btn btn-ghost" disabled>
            Учётные данные
          </button>
          <span className="muted text-sm">отключённые: одинаковые на всех уровнях</span>
        </div>
        <div className="row wrap mt-3">
          <button className="btn btn-primary btn-sm">Малая главная</button>
          <button className="btn btn-sm">Малая</button>
          <button className="btn btn-ghost btn-sm">Малая ghost</button>
          <button className="btn btn-sm" aria-busy="true" disabled>
            Проверка…
          </button>
          <button className="icon-btn" aria-label="Обновить">
            <RefreshCw size={18} />
          </button>
          <button className="icon-btn sm" aria-label="Изменить">
            <Pencil size={16} />
          </button>
          <button className="icon-btn sm danger" aria-label="Удалить">
            <Trash2 size={16} />
          </button>
          <button className="icon-btn sm" disabled aria-label="Нельзя">
            <Trash2 size={16} />
          </button>
        </div>
      </Section>

      <Section title="Поля и сегменты">
        <div className="row wrap items-end">
          <label className="field">
            <span>IP-адрес</span>
            <input className="input" placeholder="192.168.1.64" />
          </label>
          <label className="field">
            <span>С ошибкой</span>
            <input className="input" defaultValue="192.168.3" aria-invalid="true" />
          </label>
          <label className="field">
            <span>Отключено</span>
            <input className="input" defaultValue="554" disabled />
          </label>
          <label className="field">
            <span>Список</span>
            <select className="select">
              <option>Все производители</option>
            </select>
          </label>
          <div className="search grow-search">
            <Search size={15} />
            <input className="input" placeholder="Поиск" />
          </div>
        </div>
        <div className="row wrap mt-3">
          <div className="segmented" role="group">
            {[
              ["all", "Все", ""],
              ["on", "В сети", "online"],
              ["off", "Не в сети", "offline"],
              ["unk", "Не проверено", "unknown"],
            ].map(([k, label, dot]) => (
              <button key={k} aria-pressed={seg === k} onClick={() => setSeg(k)}>
                {dot && <span className={`dot ${dot}`} />}
                {label}
              </button>
            ))}
          </div>
          <label className="check">
            <input type="checkbox" defaultChecked />
            <span>Выбрана</span>
          </label>
          <label className="check">
            <input type="checkbox" />
            <span>Не выбрана</span>
          </label>
        </div>
      </Section>

      <Section title="Состояние, направление, бейджи">
        <div className="row wrap row-4">
          <span className="status-dot online">В сети</span>
          <span className="status-dot offline">Не в сети</span>
          <span className="status-dot unknown">Не проверено</span>
          <span className="status">Активен</span>
          <span className="status off">Уволен</span>
          <DirectionBadge direction="entry" />
          <DirectionBadge direction="exit" />
          <span className="badge">12 каналов</span>
          <span className="badge warn">Не активирована</span>
        </div>
      </Section>

      <Section title="Таблица">
        <div className="table-wrap">
          <table className="table devices-table">
            <thead>
              <tr>
                <th>Название</th>
                <th>Модель</th>
                <th>Адрес</th>
                <th className="num-r">Каналы</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>cam-1</td>
                <td>Hikvision DS-2CD2183G2-LI</td>
                <td className="num">192.168.3.52</td>
                <td className="num num-r">1</td>
                <td>
                  <span className="status-dot offline">Не в сети</span>
                </td>
              </tr>
              <tr className="open">
                <td>dijurka</td>
                <td>Dahua XVR</td>
                <td className="num">192.168.3.110</td>
                <td className="num num-r">12</td>
                <td>
                  <span className="status-dot online">В сети</span>
                </td>
              </tr>
              <tr className="selected">
                <td>cam-4</td>
                <td>Hikvision DS-K1TA70MI-T</td>
                <td className="num">192.168.3.81</td>
                <td className="num num-r">2</td>
                <td>
                  <span className="status-dot unknown">Не проверено</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Section>

      <div className="dev-grid">
        <Section title="Загрузка">
          <Skeleton rows={4} columns={[72, 150, 96, 64]} headers={["Название", "Модель", "Адрес", "Статус"]} />
        </Section>
        <Section title="Ошибка">
          <ErrorState title="Не удалось загрузить устройства" lastOk={Date.now() - 95_000} onRetry={() => {}} />
          <ErrorState onRetry={() => {}} />
        </Section>
        <Section title="Пусто">
          <EmptyState
            icon={Router}
            title="Устройств пока нет"
            text="Добавьте камеру или регистратор по IP или найдите их сканированием сети."
            action={
              <button className="btn btn-primary btn-sm">
                <Plus size={14} />
                Добавить
              </button>
            }
          />
          <EmptyState icon={Search} title="Ничего не найдено по «zzzz»" action={<button className="btn btn-sm">Сбросить фильтры</button>} />
        </Section>
      </div>

      <div className="dev-grid">
        <Section title="Дерево структуры">
          <OrgTree units={UNITS} selectedId={unit} onSelect={setUnit} count="camera_count" onAddChild={() => {}} onRename={() => {}} onDelete={() => {}} />
        </Section>
        <Section title="Тайл камеры: состояния без видео">
          <div className="dev-tiles">
            <div className="tile">
              <div className="tile-state">
                <span className="pulse" />
                <span>Подключение…</span>
              </div>
              <div className="hud">
                <span className="hud-chip">
                  <span className="name">E90508307</span>
                </span>
              </div>
            </div>
            <div className="tile">
              <div className="tile-state">
                <VideoOff size={22} />
                <span>Нет сигнала</span>
              </div>
              <div className="hud">
                <span className="hud-chip">
                  <span className="name">cam-1</span>
                  <DirectionBadge direction="exit" />
                </span>
              </div>
            </div>
            <div className="tile empty-slot" />
            <div className="tile empty-slot drop-target" />
          </div>
        </Section>
      </div>
    </div>
  );
}
