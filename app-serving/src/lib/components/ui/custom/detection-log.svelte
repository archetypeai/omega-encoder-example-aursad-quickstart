<script>
	/**
	 * Alarmed operations, newest first. A tightening is scored once, as a whole, so
	 * an alarm is one row. Once the labels are revealed, each row says what the
	 * operation really was, and a false alarm reads as one.
	 */
	import * as Table from '@archetypeai/ds-ui-svelte-console/primitives/table';
	import { EmptyState } from '@archetypeai/ds-ui-svelte-console/primitives/empty-state';
	import { CLASS_LABEL } from '$lib/stores/aursad.svelte.js';
	import { cn } from '$lib/utils';

	/** @type {{aursad: any, class?: string}} */
	let { aursad, class: className = '' } = $props();
	const s = $derived(aursad.state);
	const log = $derived([...s.results].filter((r) => r.alarm).reverse());
</script>

<div class={cn('min-h-0 overflow-y-auto', className)}>
	{#if log.length}
		<Table.Root>
			<Table.Header>
				<Table.Row>
					<Table.Head>#</Table.Head>
					<Table.Head>Operation</Table.Head>
					<Table.Head>Score</Table.Head>
					<Table.Head>Worst window</Table.Head>
					<Table.Head>Label</Table.Head>
				</Table.Row>
			</Table.Header>
			<Table.Body typography="mono" class="text-xs">
				{#each log as r (r.op)}
					{@const label = s.labels.revealed ? s.labels.labels[r.file] : null}
					<Table.Row>
						<Table.Cell class="text-muted-foreground">{r.op + 1}</Table.Cell>
						<Table.Cell>{r.file}</Table.Cell>
						<Table.Cell class="text-score-anomaly">{r.score.toFixed(3)}</Table.Cell>
						<Table.Cell class="text-muted-foreground">{r.worst + 1} of {r.windowScores.length}</Table.Cell>
						<Table.Cell class={label === 'normal' ? 'text-muted-foreground' : label ? 'text-score-anomaly' : 'text-muted-foreground'}>
							{label ? (label === 'normal' ? 'normal (false alarm)' : CLASS_LABEL[label]) : 'hidden'}
						</Table.Cell>
					</Table.Row>
				{/each}
			</Table.Body>
		</Table.Root>
	{:else}
		<EmptyState variant="list">No operation has crossed the threshold yet.</EmptyState>
	{/if}
</div>
