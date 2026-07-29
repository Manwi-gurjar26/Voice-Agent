"use client";

import { Controller, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ALLOWED_VOICE_IDS } from "@/lib/types";
import type { AgentCreate, AgentRead, AgentStatus, AgentUpdate, EffortLevel } from "@/lib/types";

const EFFORT_LEVELS: EffortLevel[] = ["low", "medium", "high", "xhigh", "max"];
const AGENT_STATUSES: AgentStatus[] = ["draft", "active", "disabled"];

const agentFormSchema = z.object({
  name: z.string().min(1, "Name is required.").max(120),
  greeting: z.string().max(2_000),
  system_prompt: z.string().max(100_000),
  model: z.string().max(60),
  effort: z.enum(["low", "medium", "high", "xhigh", "max"]),
  max_output_tokens: z
    .number()
    .int()
    .min(256, "Must be at least 256.")
    .max(128_000, "Must be at most 128,000."),
  voice_enabled: z.boolean(),
  voice_id: z.string(),
  primary_color: z.string(),
  position: z.enum(["bottom-right", "bottom-left"]),
  allowed_origins_text: z.string(),
  status: z.enum(["draft", "active", "disabled"]),
  rate_limit_per_minute: z.number().int().min(1, "Must be at least 1.").max(1_000, "Must be at most 1,000."),
});
export type AgentFormValues = z.infer<typeof agentFormSchema>;

export const DEFAULT_AGENT_FORM_VALUES: AgentFormValues = {
  name: "",
  greeting: "",
  system_prompt: "",
  model: "",
  effort: "medium",
  max_output_tokens: 2048,
  voice_enabled: false,
  voice_id: "",
  primary_color: "#2F6FED",
  position: "bottom-right",
  allowed_origins_text: "",
  status: "draft",
  rate_limit_per_minute: 30,
};

export function agentToFormValues(agent: AgentRead): AgentFormValues {
  return {
    name: agent.name,
    greeting: agent.greeting,
    system_prompt: agent.system_prompt,
    model: agent.model,
    effort: agent.effort,
    max_output_tokens: agent.max_output_tokens,
    voice_enabled: agent.voice_enabled,
    voice_id: agent.voice_id ?? "",
    primary_color: agent.theme.primaryColor ?? "#2F6FED",
    position: agent.theme.position === "bottom-left" ? "bottom-left" : "bottom-right",
    allowed_origins_text: agent.allowed_origins.join("\n"),
    status: agent.status,
    rate_limit_per_minute: agent.rate_limit_per_minute,
  };
}

function parseOrigins(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export function formValuesToCreate(values: AgentFormValues): AgentCreate {
  return {
    name: values.name,
    greeting: values.greeting || undefined,
    system_prompt: values.system_prompt || undefined,
    model: values.model || undefined,
    effort: values.effort,
    max_output_tokens: values.max_output_tokens,
    voice_enabled: values.voice_enabled,
    voice_id: values.voice_enabled ? values.voice_id || undefined : undefined,
    theme: { primaryColor: values.primary_color, position: values.position },
    allowed_origins: parseOrigins(values.allowed_origins_text),
  };
}

export function formValuesToUpdate(values: AgentFormValues): AgentUpdate {
  return {
    ...formValuesToCreate(values),
    status: values.status,
    rate_limit_per_minute: values.rate_limit_per_minute,
  };
}

interface AgentFormProps {
  mode: "create" | "edit";
  defaultValues: AgentFormValues;
  onSubmit: (values: AgentFormValues) => Promise<void>;
  submitting: boolean;
  submitLabel: string;
}

export function AgentForm({ mode, defaultValues, onSubmit, submitting, submitLabel }: AgentFormProps) {
  const {
    register,
    handleSubmit,
    control,
    watch,
    setValue,
    formState: { errors },
  } = useForm<AgentFormValues>({ resolver: zodResolver(agentFormSchema), defaultValues });

  const voiceEnabled = watch("voice_enabled");
  const primaryColor = watch("primary_color");

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-6">
      <section className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="name">Name</Label>
          <Input id="name" {...register("name")} />
          {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="greeting">Greeting</Label>
          <Input id="greeting" placeholder="Hi! How can I help you today?" {...register("greeting")} />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="system_prompt">System prompt</Label>
          <Textarea
            id="system_prompt"
            rows={6}
            placeholder="You are a helpful assistant."
            {...register("system_prompt")}
          />
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <Label htmlFor="model">Model (blank = platform default)</Label>
          <Input id="model" placeholder="claude-opus-5" {...register("model")} />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="effort">Effort</Label>
          <Controller
            control={control}
            name="effort"
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="effort" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EFFORT_LEVELS.map((level) => (
                    <SelectItem key={level} value={level}>
                      {level}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="max_output_tokens">Max output tokens</Label>
          <Input
            id="max_output_tokens"
            type="number"
            min={256}
            max={128_000}
            {...register("max_output_tokens", { valueAsNumber: true })}
          />
          {errors.max_output_tokens && (
            <p className="text-sm text-destructive">{errors.max_output_tokens.message}</p>
          )}
        </div>
        {mode === "edit" && (
          <div className="flex flex-col gap-2">
            <Label htmlFor="rate_limit_per_minute">Rate limit (requests/min per visitor)</Label>
            <Input
              id="rate_limit_per_minute"
              type="number"
              min={1}
              max={1_000}
              {...register("rate_limit_per_minute", { valueAsNumber: true })}
            />
            {errors.rate_limit_per_minute && (
              <p className="text-sm text-destructive">{errors.rate_limit_per_minute.message}</p>
            )}
          </div>
        )}
      </section>

      {mode === "edit" && (
        <section className="flex flex-col gap-2">
          <Label htmlFor="status">Status</Label>
          <Controller
            control={control}
            name="status"
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="status" className="w-full sm:w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {AGENT_STATUSES.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
          <p className="text-xs text-muted-foreground">Only active agents accept widget traffic.</p>
        </section>
      )}

      <section className="flex flex-col gap-4 rounded-lg border p-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <Label htmlFor="voice_enabled">Voice</Label>
            <p className="text-xs text-muted-foreground">Lets visitors speak instead of typing.</p>
          </div>
          <Controller
            control={control}
            name="voice_enabled"
            render={({ field }) => (
              <Switch id="voice_enabled" checked={field.value} onCheckedChange={field.onChange} />
            )}
          />
        </div>
        {voiceEnabled && (
          <div className="flex flex-col gap-2">
            <Label htmlFor="voice_id">Voice</Label>
            <Controller
              control={control}
              name="voice_id"
              render={({ field }) => (
                <Select value={field.value || undefined} onValueChange={field.onChange}>
                  <SelectTrigger id="voice_id" className="w-full sm:w-48">
                    <SelectValue placeholder="Default (alloy)" />
                  </SelectTrigger>
                  <SelectContent>
                    {ALLOWED_VOICE_IDS.map((voiceId) => (
                      <SelectItem key={voiceId} value={voiceId}>
                        {voiceId}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </div>
        )}
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <Label htmlFor="primary_color">Primary color</Label>
          <div className="flex items-center gap-2">
            <input
              type="color"
              aria-label="Primary color picker"
              value={/^#[0-9a-fA-F]{6}$/.test(primaryColor) ? primaryColor : "#2f6fed"}
              onChange={(e) => setValue("primary_color", e.target.value)}
              className="h-8 w-10 rounded border"
            />
            <Input id="primary_color" {...register("primary_color")} />
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="position">Widget position</Label>
          <Controller
            control={control}
            name="position"
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="position" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="bottom-right">Bottom right</SelectItem>
                  <SelectItem value="bottom-left">Bottom left</SelectItem>
                </SelectContent>
              </Select>
            )}
          />
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <Label htmlFor="allowed_origins_text">Allowed origins (one per line)</Label>
        <Textarea
          id="allowed_origins_text"
          rows={3}
          placeholder={"https://example.com\nhttps://www.example.com"}
          {...register("allowed_origins_text")}
        />
        <p className="text-xs text-muted-foreground">
          The widget refuses to load anywhere not listed here. Leave empty and it embeds nowhere.
        </p>
      </section>

      <Button type="submit" disabled={submitting} className="self-start">
        {submitting ? "Saving…" : submitLabel}
      </Button>
    </form>
  );
}
