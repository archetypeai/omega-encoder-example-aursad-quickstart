<script>
	/**
	 * Settings, in the LARCO monitor's shape: what the serving agent is doing, the replay's
	 * pace and labels, this replay's counts, and the live data flow. Nothing here changes
	 * the detector.
	 */
	import * as Dialog from '@archetypeai/ds-ui-svelte-console/primitives/dialog';
	import * as Tabs from '@archetypeai/ds-ui-svelte-console/primitives/tabs';
	import { Button } from '@archetypeai/ds-ui-svelte-console/primitives/button';
	import { Badge } from '@archetypeai/ds-ui-svelte-console/primitives/badge';
	import { Label } from '@archetypeai/ds-ui-svelte-console/primitives/label';
	import EyeIcon from '@lucide/svelte/icons/eye';
	import RotateCcwIcon from '@lucide/svelte/icons/rotate-ccw';
	import { TOPICS, CLASS_LABEL } from '$lib/stores/aursad.svelte.js';
	import DataFlow from './data-flow.svelte';

	/** @type {{aursad: any, open?: boolean}} */
	let { aursad, open = $bindable(false) } = $props();
	const s = $derived(aursad.state);
	const st = $derived(s.status);
	const a = $derived(s.agent);
	const det = $derived(a?.detector);
	const t = $derived(aursad.totals);
	const errors = $derived(s.results.filter((/** @type {any} */ r) => r.error).length);
	const PROSE = 'max-w-prose text-xs text-muted-foreground';
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="sm:max-w-4xl">
		<Dialog.Header>
			<Dialog.Title>Settings</Dialog.Title>
			<Dialog.Description>
				The replay's pace and labels, and what the serving agent is doing. Nothing here changes the
				detector.
			</Dialog.Description>
		</Dialog.Header>
		<Dialog.Body class="space-y-5">
			<section class="space-y-2">
				<Label variant="sectionHeader">Agent</Label>
				<div class="flex flex-wrap items-center gap-x-6 gap-y-1 font-mono text-xs">
					<Badge variant="status" class={a?.phase === 'running' ? 'text-atai-good' : 'text-atai-warning'}>{a?.phase ?? 'no bridge'}</Badge>
					<span><span class="text-muted-foreground">session</span> {a?.session ?? '—'}</span>
					<span><span class="text-muted-foreground">deployment</span> {a?.deployment ?? '—'}</span>
					<span><span class="text-muted-foreground">median query</span> {a?.medianLatencyMs != null ? `${a.medianLatencyMs} ms` : '—'}</span>
				</div>
				<p class="font-mono text-xs text-muted-foreground">
					{a?.package ?? ''}{a?.package ? ' · omega-aursad, as shipped' : ''}{a?.window ? ` · session values window_size ${a.window}, step_size ${a.window}` : ''}
				</p>
				<p class={PROSE}>
					{#if det}
						Scored in the bridge by the kNN Stage 5 froze: {det.group}, PCA {det.pca || 'none'}, k {det.k},
						match {det.match}; threshold {det.threshold.toFixed(4)} (validation AUROC {det.validationAuroc}).
					{/if}
					{#if a?.detail}{a.detail}{/if}
				</p>
			</section>

			<section class="space-y-2">
				<Label variant="sectionHeader">Pace</Label>
				<div class="flex flex-wrap items-center gap-4">
					<Tabs.Root value={String(st?.pace ?? 4)} onValueChange={(/** @type {string} */ v) => aursad.setPace(Number(v))}>
						<Tabs.List variant="segmented">
							{#each ['1', '4', '16'] as v (v)}
								<Tabs.Trigger value={v}>{v === '1' ? 'Real time' : `${v}×`}</Tabs.Trigger>
							{/each}
						</Tabs.List>
					</Tabs.Root>
					<Button variant="outline" size="sm" disabled={!s.connected} onclick={() => aursad.restart()}>
						<RotateCcwIcon aria-hidden="true" />Restart the replay
					</Button>
				</div>
				<p class={PROSE}>
					How fast a tightening's rows are sent: real time is 10.24 s a tightening. The replayer waits
					for each answer (~1.3 s) before the next, so a tightening scores the same at any pace.
				</p>
			</section>

			<section class="space-y-2">
				<Label variant="sectionHeader">Labels</Label>
				<div class="flex flex-wrap items-center gap-4">
					<Button variant="outline" size="sm" disabled={!s.connected || s.labels.revealed} onclick={() => aursad.reveal()}>
						<EyeIcon aria-hidden="true" />Reveal labels
					</Button>
					<span class="font-mono text-xs">{s.labels.revealed ? 'revealed' : 'held back'}</span>
				</div>
				<p class={PROSE}>
					Held back, as in Stage 7: revealed for the tightenings played so far when you ask, or at the
					end of the replay. They never colour a call.
				</p>
			</section>

			<section class="space-y-2">
				<Label variant="sectionHeader">This replay</Label>
				<dl class="flex flex-wrap gap-x-6 gap-y-1 font-mono text-sm">
					<div class="flex gap-1.5"><dt class="text-muted-foreground">scored</dt><dd>{t.scored} / {st?.opCount ?? '—'}</dd></div>
					<div class="flex gap-1.5"><dt class="text-muted-foreground">alarms</dt><dd>{t.alarms}</dd></div>
					<div class="flex gap-1.5"><dt class="text-muted-foreground">errors</dt><dd class={errors ? 'text-atai-warning' : ''}>{errors}</dd></div>
					{#if t.truth}
						<div class="flex gap-1.5"><dt class="text-muted-foreground">caught</dt><dd>{t.truth.caught} / {t.truth.anomalies}</dd></div>
						<div class="flex gap-1.5"><dt class="text-muted-foreground">false alarms</dt><dd>{t.truth.falseAlarms} / {t.truth.normals}</dd></div>
					{/if}
				</dl>
				<p class={PROSE}>
					{#if t.truth}
						By type: {Object.entries(t.truth.byClass).map(([c, v]) => `${CLASS_LABEL[c] ?? c} ${v.caught}/${v.total}`).join(', ')}.
					{/if}
					An error is a tightening the platform didn't answer, or answered with the wrong number of
					windows (the serving bridge's log says which).
				</p>
			</section>

			<section class="space-y-2">
				<Label variant="sectionHeader">Live data flow</Label>
				<div class="grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-xs sm:grid-cols-4">
					{#each TOPICS as topic (topic)}
						{@const r = s.flows[topic] ?? 0}
						<span class={r > 0 ? 'text-atai-good' : 'text-muted-foreground'}>{topic} {r > 0 ? `${r < 10 ? r.toFixed(1) : Math.round(r)}/s` : 'idle'}</span>
					{/each}
				</div>
				<DataFlow {aursad} />
			</section>
		</Dialog.Body>
	</Dialog.Content>
</Dialog.Root>
