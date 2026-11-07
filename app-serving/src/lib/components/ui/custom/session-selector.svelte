<script>
	/**
	 * Which of the delivery's recording sessions is replayed: all five (14-18), or one.
	 * The name says nothing about which faults are in it: the labels stay held back.
	 */
	import * as Select from '@archetypeai/ds-ui-svelte-console/primitives/select';

	/** @type {{aursad: any}} */
	let { aursad } = $props();
	const st = $derived(aursad.state.status);
	const sessions = $derived(st?.sessions ?? []);
	const value = $derived(st?.session == null ? 'all' : String(st.session));
	const label = $derived(st?.session == null ? 'Sessions 14–18' : `Session ${st.session}`);
</script>

<Select.Root
	type="single"
	{value}
	onValueChange={(/** @type {string} */ v) => v && aursad.select(v === 'all' ? 'all' : Number(v))}
	disabled={!aursad.state.connected || !sessions.length}
>
	<Select.Trigger size="sm" typography="mono" class="max-w-72" aria-label="Recording session">
		<span class="truncate">{label}</span>
	</Select.Trigger>
	<Select.Content>
		<Select.Item value="all" label="Sessions 14–18" typography="mono">
			<span class="flex w-full justify-between gap-4">
				<span>Sessions 14–18</span>
				<span class="text-muted-foreground">{st?.totalOperations ?? '—'} tightenings</span>
			</span>
		</Select.Item>
		{#each sessions as s (s.id)}
			<Select.Item value={String(s.id)} label={`Session ${s.id}`} typography="mono">
				<span class="flex w-full justify-between gap-4">
					<span>Session {s.id}</span>
					<span class="text-muted-foreground">{s.operations} tightenings</span>
				</span>
			</Select.Item>
		{/each}
	</Select.Content>
</Select.Root>
