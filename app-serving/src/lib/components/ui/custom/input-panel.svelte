<script>
	/**
	 * What goes INTO the agent: the robot cell's 12 signals, one tightening at a time.
	 * Left side of the workbench, in the LARCO monitor's shape: the session selector in
	 * the caption, the channels, and the replay's position under them.
	 */
	import Pane from '$lib/components/ui/patterns/pane/index.js';
	import CircleArrowUpIcon from '@lucide/svelte/icons/circle-arrow-up';
	import * as Tooltip from '@archetypeai/ds-ui-svelte-console/primitives/tooltip';
	import { Progress } from '@archetypeai/ds-ui-svelte-console/primitives/progress';
	import ChannelGrid from './channel-grid.svelte';
	import SessionSelector from './session-selector.svelte';

	/** @type {{aursad: any, class?: string}} */
	let { aursad, class: className = '' } = $props();
	const s = $derived(aursad.state);
	const st = $derived(s.status);
	const SUBTITLE = 'AURSAD · UR3e + OnRobot screwdriver · 12 channels @ 100 Hz';
	const op = $derived(st ? Math.min(st.op + 1, st.opCount) : 0);
	const pace = $derived(
		!st
			? 'No replayer'
			: st.ended
				? 'ended; labels revealed'
				: st.playing
					? `${st.pace === 1 ? 'real time' : `${st.pace}× real time`}, waiting for each answer before the next tightening`
					: 'paused'
	);
</script>

<Pane variant="panel" title="Input" icon={CircleArrowUpIcon} subtitle={SUBTITLE} class="min-h-0 {className}">
	{#snippet actions()}
		<SessionSelector {aursad} />
	{/snippet}

	<div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
		<Pane title="Tightening" class="min-h-0 flex-1">
			{#snippet titleAfter()}
				<Tooltip.Root>
					<Tooltip.Trigger variant="info" aria-label="About this tightening" />
					<Tooltip.Content class="max-w-xs">
						One tightening (one screw driven), replayed in recording order: 1,024 rows (10.24 s),
						starting 256 rows before the screwdriver's torque rises. Traces are in library sigmas, the
						z-scored values the agent receives, on one scale; the figure on the right is the latest
						value in the channel's own units. The dashed sections are the agent's windows; the shaded
						one set the tightening's score.
					</Tooltip.Content>
				</Tooltip.Root>
			{/snippet}
			{#snippet actions()}
				<span class="font-mono text-xs text-muted-foreground">{s.current.file || '—'}</span>
			{/snippet}
			<ChannelGrid {aursad} class="min-h-0 flex-1" />
		</Pane>
		<Pane title="Replay" class="border-t border-border">
			<div class="flex items-center gap-4">
				<span class="shrink-0 font-mono text-sm tabular-nums">
					{op} <span class="text-muted-foreground">/ {st?.opCount ?? '—'}</span>
				</span>
				<Progress value={st?.opCount ? (100 * (st.op + s.current.rows / 1024)) / st.opCount : 0} size="sm" class="flex-1" aria-label="Position in the replay" />
				<span class="shrink-0 font-mono text-xs text-muted-foreground tabular-nums">
					row {s.current.rows.toLocaleString()} of 1,024
				</span>
			</div>
			<p class="text-xs text-muted-foreground">{pace}</p>
		</Pane>
	</div>
</Pane>
