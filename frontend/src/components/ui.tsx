import { Button, Chip, Skeleton, Table } from "@heroui/react";
import type { ReactNode } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CircleAlert,
  Inbox,
  RotateCw,
} from "lucide-react";
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <h1 className="page-title">{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      <div className="page-actions">{actions}</div>
    </header>
  );
}
export function Panel({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {title && <h2 className="panel-title">{title}</h2>}
      <div className="panel-body">{children}</div>
    </section>
  );
}
export function ErrorNotice({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  if (!error) return null;
  return (
    <div role="alert" className="notice error">
      <CircleAlert size={17} />
      <span>{error instanceof Error ? error.message : String(error)}</span>
      {retry && (
        <Button size="sm" variant="ghost" onPress={retry}>
          <RotateCw size={14} />
          重试
        </Button>
      )}
    </div>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="empty-state">
      <Inbox size={26} />
      <p>{children}</p>
    </div>
  );
}
export function DataTable({ columns, rows, numericColumns = [] }: { columns: string[]; rows: ReactNode[][]; numericColumns?: number[] }) {
  return <Table className="table-wrap"><Table.ScrollContainer>
    <Table.Content aria-label={columns.join("、")} className="data-table">
      <Table.Header>{columns.map((column, index) => <Table.Column key={index} id={String(index)} isRowHeader={index === 0} className={numericColumns.includes(index) ? "numeric-column" : undefined}>{column}</Table.Column>)}</Table.Header>
      <Table.Body renderEmptyState={() => <Empty>暂无可显示的记录。</Empty>}>{rows.map((row, index) => <Table.Row key={index} id={String(index)}>{row.map((cell, col) => <Table.Cell key={col} textValue={typeof cell === "string" || typeof cell === "number" ? String(cell) : columns[col]} className={numericColumns.includes(col) ? "numeric-column" : undefined}>{cell}</Table.Cell>)}</Table.Row>)}</Table.Body>
    </Table.Content>
  </Table.ScrollContainer></Table>;
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
export function Status({ value }: { value: unknown }) {
  const text = String(value ?? "未知"),
    good = [
      "active",
      "enabled",
      "succeeded",
      "completed",
      "ready",
      "ai",
      "satisfied",
      "open",
    ].includes(text),
    bad = [
      "failed",
      "revoked",
      "disabled",
      "inactive",
      "deleting",
      "timed_out",
    ].includes(text);
  return (
    <Chip
      size="sm"
      variant="soft"
      color={good ? "success" : bad ? "danger" : "default"}
    >
      {text}
    </Chip>
  );
}
export function JsonView({ value }: { value: unknown }) {
  return <pre className="json-view">{JSON.stringify(value, null, 2)}</pre>;
}
export function Pager({
  offset,
  count,
  size,
  onChange,
}: {
  offset: number;
  count: number;
  size: number;
  onChange: (offset: number) => void;
}) {
  return (
    <div className="pager">
      <span>
        {count ? `${offset + 1}–${offset + count} 项` : "本页无记录"}
      </span>
      <Button
        size="sm"
        variant="ghost"
        isDisabled={!offset}
        onPress={() => onChange(Math.max(0, offset - size))}
      >
        <ArrowLeft size={15} />
        上一页
      </Button>
      <Button
        size="sm"
        variant="ghost"
        isDisabled={count < size}
        onPress={() => onChange(offset + size)}
      >
        下一页
        <ArrowRight size={15} />
      </Button>
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading-stack" aria-label="正在加载" role="status">
      {[1, 2, 3].map((i) => (
        <Skeleton key={i} className="skeleton" />
      ))}
    </div>
  );
}
