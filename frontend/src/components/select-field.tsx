"use client";

import type { ReactNode } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/** App-level composition of shadcn Select, shared by filters and forms. */
export function SelectField({
  value,
  onValueChange,
  options,
  label,
  disabled,
  id,
  className,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: { value: string; label: ReactNode }[];
  label: string;
  disabled?: boolean;
  id?: string;
  className?: string;
}) {
  return (
    <Select value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectTrigger id={id} aria-label={label} className={className}>
        <SelectValue>
          {options.find((option) => option.value === value)?.label}
        </SelectValue>
      </SelectTrigger>
      <SelectContent position="popper" align="start">
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
