import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Plus, Search, UserRound } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { keys, useUnits } from "../api/queries";
import { LEVELS, type Employee, type OrgLevel } from "../api/types";
import { EmployeeModal } from "../components/EmployeeModal";
import { Confirm, Modal } from "../components/Modal";
import { Thumb } from "../components/NoImage";
import { EmptyState, ErrorState, Skeleton } from "../components/States";
import { UnitPicker } from "../components/UnitPicker";
import { errorText } from "../lib/errors";
import { isAdmin, useAuth, useUi } from "../lib/store";
import { type TreeNode, unitPath } from "../lib/tree";

const PAGE = 50;

type UnitDialog =
  | { kind: "create"; parentId: string | null; level: OrgLevel }
  | { kind: "rename"; unit: TreeNode }
  | { kind: "delete"; unit: TreeNode };

function initials(name: string) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

export function OrgPage() {
  const { t } = useTranslation();
  const admin = isAdmin(useAuth((s) => s.user));
  const { data: units = [], isSuccess: unitsLoaded, isPending: unitsLoading } = useUnits();
  const [unitId, setUnitId] = useState<string | null>(null);
  const [dialog, setDialog] = useState<UnitDialog | null>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<boolean | undefined>(undefined);
  const [limit, setLimit] = useState(PAGE);
  const [editing, setEditing] = useState<Employee | "new" | null>(null);

  const unitNames = useMemo(() => new Map(units.map((u) => [u.id, u.name])), [units]);

  const employees = useQuery({
    queryKey: [...keys.employees, unitId, query, active, limit],
    queryFn: () => api.employees({ org_unit_id: unitId, q: query, active, limit }),
    placeholderData: keepPreviousData,
  });
  const items = employees.data?.items ?? [];
  const total = employees.data?.total ?? 0;
  const hasData = employees.data !== undefined;
  const filtered = query !== "" || active !== undefined;
  const resetFilters = () => {
    setQuery("");
    setActive(undefined);
    setLimit(PAGE);
  };
  const headers = [
    t("employee.fullName"),
    t("employee.personnelNumber"),
    t("employee.position"),
    t("employee.unit"),
    t("org.status"),
  ];

  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("nav.org")}</h1>
        {hasData && <span className="muted num">{total}</span>}
        <span className="spacer" />
        {admin && units.length > 0 && (
          <button className="btn btn-primary" onClick={() => setEditing("new")}>
            <Plus size={16} />
            {t("org.addEmployee")}
          </button>
        )}
      </div>

      <div className="filters">
        <UnitPicker
          variant="popover"
          units={units}
          loading={unitsLoading}
          selectedId={unitId}
          onSelect={(id) => {
            setUnitId(id);
            setLimit(PAGE);
          }}
          count="employee_count"
          allLabel={t("org.allEmployees")}
          onAddChild={
            admin
              ? (p) => setDialog({ kind: "create", parentId: p.id, level: LEVELS[LEVELS.indexOf(p.level) + 1] })
              : undefined
          }
          onRename={admin ? (u) => setDialog({ kind: "rename", unit: u }) : undefined}
          onDelete={admin ? (u) => setDialog({ kind: "delete", unit: u }) : undefined}
          footer={
            <>
              {unitsLoaded && units.length === 0 && <p className="state-text">{t("org.emptyStructure")}</p>}
              {admin && (
                <button
                  className="btn btn-sm"
                  onClick={() => setDialog({ kind: "create", parentId: null, level: "company" })}
                >
                  <Building2 size={14} />
                  {t("org.addCompany")}
                </button>
              )}
            </>
          }
        />
        <div className="search grow-search">
          <Search size={15} />
          <input
            className="input"
            placeholder={t("common.search")}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setLimit(PAGE);
            }}
          />
        </div>
        <div className="segmented" role="group" aria-label={t("org.status")}>
          {[
            { v: undefined, label: t("common.all") },
            { v: true, label: t("common.active") },
            { v: false, label: t("common.inactive") },
          ].map((o) => (
            <button key={String(o.v)} aria-pressed={active === o.v} onClick={() => setActive(o.v)}>
              {o.v !== undefined && <i className={`dot ${o.v ? "online" : "unknown"}`} />}
              {o.label}
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        {employees.isPending ? (
          <Skeleton rows={6} columns={[180, 64, 140, 110, 72]} headers={headers} />
        ) : employees.isError && !hasData ? (
          <ErrorState
            title={t("org.loadFailed")}
            lastOk={employees.dataUpdatedAt}
            onRetry={() => employees.refetch()}
            retrying={employees.isFetching}
          />
        ) : items.length === 0 ? (
          filtered ? (
            <EmptyState
              icon={Search}
              title={t("org.noMatches")}
              action={
                <button className="btn btn-sm" onClick={resetFilters}>
                  {t("states.resetFilters")}
                </button>
              }
            />
          ) : (
            <EmptyState
              icon={UserRound}
              title={t("org.emptyEmployees")}
              action={
                admin &&
                units.length > 0 && (
                  <button className="btn btn-primary btn-sm" onClick={() => setEditing("new")}>
                    <Plus size={14} />
                    {t("org.addEmployee")}
                  </button>
                )
              }
            />
          )
        ) : (
          <div className="table-wrap">
            {employees.isError && (
              <ErrorState
                title={t("org.loadFailed")}
                lastOk={employees.dataUpdatedAt}
                onRetry={() => employees.refetch()}
                retrying={employees.isFetching}
              />
            )}
            <table className="table staff-table">
              <colgroup>
                <col className="col-person" />
                <col className="col-number" />
                <col className="col-position" />
                <col className="col-unit" />
                <col className="col-status" />
              </colgroup>
              <thead>
                <tr>
                  <th>{t("employee.fullName")}</th>
                  <th className="num-r">{t("employee.personnelNumber")}</th>
                  <th>{t("employee.position")}</th>
                  <th>{t("employee.unit")}</th>
                  <th>{t("org.status")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((e) => (
                  <tr
                    key={e.id}
                    className={`${e.is_active ? "" : "inactive"}${admin ? "" : " readonly"}`}
                    onClick={() => admin && setEditing(e)}
                  >
                    <td>
                      <span className="person" title={e.full_name}>
                        {e.photos[0] ? (
                          <Thumb className="avatar" src={e.photos[0].url} compact />
                        ) : (
                          <span className="avatar">{initials(e.full_name)}</span>
                        )}
                        <span className="person-name">{e.full_name}</span>
                      </span>
                    </td>
                    <td className="num num-r">{e.personnel_number}</td>
                    <td title={e.position}>{e.position}</td>
                    <td className="muted" title={unitPath(units, e.org_unit_id)}>
                      {unitNames.get(e.org_unit_id)}
                    </td>
                    <td>
                      <span className={`status${e.is_active ? "" : " off"}`}>
                        {e.is_active ? t("common.active") : t("common.inactive")}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="table-foot">
              <span>{t("org.shownOf", { shown: items.length, count: total })}</span>
              {items.length < total && (
                <button className="btn btn-ghost btn-sm" onClick={() => setLimit((l) => l + PAGE)}>
                  {t("common.loadMore")}
                </button>
              )}
              {filtered && (
                <button className="btn btn-ghost btn-sm" onClick={resetFilters}>
                  {t("states.resetFilters")}
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {dialog && (
        <UnitDialogView
          dialog={dialog}
          onClose={() => setDialog(null)}
          onCreated={setUnitId}
          onDeleted={(id) => id === unitId && setUnitId(null)}
        />
      )}
      {editing && (
        <EmployeeModal
          employee={editing === "new" ? undefined : editing}
          defaultUnitId={unitId}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

interface UnitDialogProps {
  dialog: UnitDialog;
  onClose: () => void;
  onCreated: (id: string) => void;
  onDeleted: (id: string) => void;
}

function UnitDialogView({ dialog, onClose, onCreated, onDeleted }: UnitDialogProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const notify = useUi((s) => s.notify);
  const [name, setName] = useState(dialog.kind === "rename" ? dialog.unit.name : "");

  const mutation = useMutation({
    mutationFn: async () => {
      if (dialog.kind === "create") return api.createUnit(name.trim(), dialog.parentId);
      if (dialog.kind === "rename") return api.renameUnit(dialog.unit.id, name.trim());
      await api.deleteUnit(dialog.unit.id);
    },
    onSuccess: async (unit) => {
      await qc.invalidateQueries({ queryKey: keys.units });
      // Selecting the new unit expands the tree down to it, so it is visible
      // even when its parent was collapsed.
      if (dialog.kind === "create" && unit) onCreated(unit.id);
      if (dialog.kind === "delete") {
        onDeleted(dialog.unit.id);
        notify(t("org.deleted"));
      }
      onClose();
    },
  });
  const error = mutation.error ? errorText(t, mutation.error) : "";

  if (dialog.kind === "delete") {
    return (
      <Confirm
        text={t("org.deleteConfirm", { name: dialog.unit.name })}
        confirmLabel={t("common.delete")}
        onConfirm={() => mutation.mutate()}
        onClose={onClose}
        busy={mutation.isPending}
        error={error}
      />
    );
  }

  const title = dialog.kind === "create" ? t(`addChild.${dialog.level}`) : t("org.rename");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate();
  };

  return (
    <Modal
      title={title}
      onClose={onClose}
      narrow
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button
            className="btn btn-primary"
            type="submit"
            form="unit-form"
            disabled={mutation.isPending || !name.trim()}
          >
            {t("common.save")}
          </button>
        </>
      }
    >
      <form id="unit-form" className="form-grid" onSubmit={submit}>
        <label className="field wide">
          <span>{t("org.newName")}</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </Modal>
  );
}
