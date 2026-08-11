"use client";

import { Controller, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Globe, Mic, Palette, Settings2, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
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

/** One titled panel of related fields. Replaces the previous flat run of
 * ~12 unlabelled field groups, which gave no clue which settings affected
 * the model versus the widget's appearance. */
function FormSection({
  icon: Icon,
  title,
  description,
  children,
  className,
}: {
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  title: string;
  description: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className="bg-card/60 elev-1 overflow-hidden rounded-2xl border backdrop-blur-sm">
      <div className="flex items-start gap-3 border-b px-5 py-4">
        <span className="bg-primary/10 text-primary mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg">
          <Icon className="size-4" aria-hidden={true} />
        </span>
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          <p className="text-muted-foreground text-xs">{description}</p>
        </div>
      </div>
      <div className={cn("p-5", className)}>{children}</div>
    </section>
  );
}

/** A miniature of what the visitor will actually see, driven live by the
 * colour and position fields. Those two settings are otherwise invisible
 * until the agent is embedded on a real site and reloaded. */
function WidgetPreview({
  color,
  position,
  greeting,
}: {
  color: string;
  position: "bottom-right" | "bottom-left";
  greeting: string;
}) {
  const safeColor = /^#[0-9a-fA-F]{6}$/.test(color) ? color : "#2F6FED";
  return (
    <div
      aria-hidden="true"
      className="bg-muted/40 relative h-52 select-none overflow-hidden rounded-xl border"
    >
      <div className="bg-card/70 flex items-center gap-1.5 border-b px-3 py-2">
        {["#ef4444", "#eab308", "#22c55e"].map((c) => (
          <span key={c} className="size-2 rounded-full" style={{ background: c }} />
        ))}
        <span className="bg-muted ml-2 h-3 flex-1 rounded-full" />
      </div>
      <div className="flex flex-col gap-2 p-4">
        <span className="bg-foreground/10 h-2.5 w-1/3 rounded-full" />
        <span className="bg-foreground/[0.07] h-2 w-full rounded-full" />
        <span className="bg-foreground/[0.07] h-2 w-4/5 rounded-full" />
        <span className="bg-foreground/[0.07] h-2 w-2/3 rounded-full" />
      </div>
      <div
        className={cn(
          "absolute bottom-3 flex flex-col items-end gap-2",
          position === "bottom-left" ? "left-3 items-start" : "right-3 items-end",
        )}
      >
        <span
          className="elev-2 max-w-[13rem] truncate rounded-2xl px-3 py-2 text-[11px] text-white"
          style={{ background: safeColor }}
        >
          {greeting || "Hi! How can I help you today?"}
        </span>
        <span
          className="elev-2 grid size-10 place-items-center rounded-full text-white"
          style={{ background: safeColor }}
        >
          <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor">
            <path d="M4 4h16v12H7.5L4 19.5V4z" strokeWidth="2" strokeLinejoin="round" />
          </svg>
        </span>
      </div>
    </div>
  );
}

export function AgentForm({ mode, defaultValues, onSubmit, submitting, submitLabel }: AgentFormProps) {
  const {
    register,
    handleSubmit,
    control,
    setValue,
    formState: { errors },
  } = useForm<AgentFormValues>({ resolver: zodResolver(agentFormSchema), defaultValues });

  // useWatch, not form.watch(): watch() re-reads on every render in a way
  // the React Compiler can't track (it flags the call as an incompatible
  // library API), whereas useWatch is a real subscription hook.
  const voiceEnabled = useWatch({ control, name: "voice_enabled" });
  const primaryColor = useWatch({ control, name: "primary_color" });
  const greeting = useWatch({ control, name: "greeting" });
  const position = useWatch({ control, name: "position" });

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-5">
      <FormSection
        icon={Sparkles}
        title="Identity"
        description="What the agent is called and how it introduces itself."
        className="flex flex-col gap-4"
      >
        <div className="flex flex-col gap-2">
          <Label htmlFor="name">Name</Label>
          <Input id="name" className="h-10" aria-invalid={errors.name ? true : undefined} {...register("name")} />
          {errors.name && <p className="text-destructive text-sm">{errors.name.message}</p>}
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="greeting">Greeting</Label>
          <Input
            id="greeting"
            className="h-10"
            placeholder="Hi! How can I help you today?"
            {...register("greeting")}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="system_prompt">System prompt</Label>
          <Textarea
            id="system_prompt"
            rows={6}
            placeholder="You are a helpful assistant."
            className="font-mono text-xs leading-relaxed"
            {...register("system_prompt")}
          />
        </div>
      </FormSection>

      <FormSection
        icon={Settings2}
        title="Model and behaviour"
        description="How much reasoning each reply gets, and how long it can run."
        className="grid gap-4 sm:grid-cols-2"
      >
        <div className="flex flex-col gap-2">
          <Label htmlFor="model">Model (blank = platform default)</Label>
          <Input id="model" className="h-10 font-mono text-xs" placeholder="llama-3.3-70b-versatile" {...register("model")} />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="effort">Effort</Label>
          <Controller
            control={control}
            name="effort"
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="effort" className="h-10 w-full capitalize">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EFFORT_LEVELS.map((level) => (
                    <SelectItem key={level} value={level} className="capitalize">
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
            className="h-10 tabular-nums"
            aria-invalid={errors.max_output_tokens ? true : undefined}
            {...register("max_output_tokens", { valueAsNumber: true })}
          />
          {errors.max_output_tokens && (
            <p className="text-destructive text-sm">{errors.max_output_tokens.message}</p>
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
              className="h-10 tabular-nums"
              aria-invalid={errors.rate_limit_per_minute ? true : undefined}
              {...register("rate_limit_per_minute", { valueAsNumber: true })}
            />
            {errors.rate_limit_per_minute && (
              <p className="text-destructive text-sm">{errors.rate_limit_per_minute.message}</p>
            )}
          </div>
        )}
      </FormSection>

      <FormSection
        icon={Mic}
        title="Voice"
        description="Let visitors speak their question and hear the answer back."
        className="flex flex-col gap-4"
      >
        <div className="bg-muted/40 flex items-center justify-between gap-4 rounded-xl px-4 py-3">
          <div>
            <Label htmlFor="voice_enabled">Voice</Label>
            <p className="text-muted-foreground text-xs">Lets visitors speak instead of typing.</p>
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
            <Label htmlFor="voice_id">Voice (Fish Audio reference ID, optional)</Label>
            <Input
              id="voice_id"
              className="h-10 w-full font-mono text-xs sm:w-80"
              placeholder="Leave blank for the default voice"
              {...register("voice_id")}
            />
          </div>
        )}
      </FormSection>

      <FormSection
        icon={Palette}
        title="Appearance"
        description="How the widget looks on your visitors' screens."
        className="grid gap-5 lg:grid-cols-2"
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="primary_color">Primary color</Label>
            <div className="flex items-center gap-2">
              <input
                type="color"
                aria-label="Primary color picker"
                value={/^#[0-9a-fA-F]{6}$/.test(primaryColor) ? primaryColor : "#2f6fed"}
                onChange={(e) => setValue("primary_color", e.target.value)}
                className="size-10 cursor-pointer rounded-lg border bg-transparent p-1"
              />
              <Input id="primary_color" className="h-10 font-mono text-xs" {...register("primary_color")} />
            </div>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="position">Widget position</Label>
            <Controller
              control={control}
              name="position"
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="position" className="h-10 w-full">
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
        </div>
        <WidgetPreview color={primaryColor} position={position} greeting={greeting} />
      </FormSection>

      <FormSection
        icon={Globe}
        title="Deployment"
        description="Where this agent is allowed to run, and whether it is live."
        className="flex flex-col gap-4"
      >
        {mode === "edit" && (
          <div className="flex flex-col gap-2">
            <Label htmlFor="status">Status</Label>
            <Controller
              control={control}
              name="status"
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="status" className="h-10 w-full capitalize sm:w-48">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {AGENT_STATUSES.map((s) => (
                      <SelectItem key={s} value={s} className="capitalize">
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            <p className="text-muted-foreground text-xs">
              Only active agents accept widget traffic.
            </p>
          </div>
        )}
        <div className="flex flex-col gap-2">
          <Label htmlFor="allowed_origins_text">Allowed origins (one per line)</Label>
          <Textarea
            id="allowed_origins_text"
            rows={3}
            placeholder={"https://example.com\nhttps://www.example.com"}
            className="font-mono text-xs"
            {...register("allowed_origins_text")}
          />
          <p className="text-muted-foreground text-xs">
            The widget refuses to load anywhere not listed here. Leave empty and it embeds
            nowhere.
          </p>
        </div>
      </FormSection>

      {/* Sticky so the save action stays reachable on a form this tall.
          Near-opaque on purpose: this overlays scrolling content, and at the
          usual glass opacity the section headings underneath showed straight
          through the bar's own text. */}
      <div className="bg-card/95 elev-3 sticky bottom-4 z-10 flex items-center justify-between gap-4 rounded-2xl border px-4 py-3 backdrop-blur-xl">
        <p className="text-muted-foreground hidden text-xs sm:block">
          Changes apply to every site embedding this agent.
        </p>
        <Button
          type="submit"
          disabled={submitting}
          className="bg-brand-gradient elev-2 ml-auto h-10 border-0 text-white hover:opacity-95"
        >
          {submitting ? "Saving…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
