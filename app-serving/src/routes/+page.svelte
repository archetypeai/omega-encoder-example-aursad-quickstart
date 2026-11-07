<script>
	/**
	 * Omega AURSAD Monitor: what goes into the agent on the left (the robot cell's 12
	 * signals, one tightening at a time), what comes out on the right (the agent's
	 * embeddings, scored by the frozen kNN detector).
	 *
	 * The agent runs on the Archetype AI platform: mosquitto carries the data, the
	 * serving bridge (scripts/serving-bridge.js) sends each tightening to a serving
	 * session of the Omega Encoder agent and scores the answer, and this page
	 * subscribes to the broker. The API key stays with the bridge.
	 */
	import { onMount, onDestroy } from 'svelte';
	import Menubar from '@archetypeai/ds-ui-svelte-labs/primitives/menubar';
	import { Badge } from '@archetypeai/ds-ui-svelte-console/primitives/badge';
	import { aursad } from '$lib/stores/aursad.svelte.js';
	import InputPanel from '$lib/components/ui/custom/input-panel.svelte';
	import OutputPanel from '$lib/components/ui/custom/output-panel.svelte';
	import SettingsDialog from '$lib/components/ui/custom/settings-dialog.svelte';

	let settingsOpen = $state(false);
	const s = $derived(aursad.state);
	const phase = $derived(!s.connected ? 'no broker' : (s.agent?.phase ?? 'no agent'));
	const tone = $derived(
		phase === 'running'
			? 'text-atai-good'
			: phase === 'no broker' || phase === 'stopped' || phase === 'no agent'
				? 'text-atai-critical'
				: 'text-atai-warning'
	);

	onMount(() => aursad.connect());
	onDestroy(() => aursad.disconnect());
</script>

<svelte:head><title>Omega AURSAD Monitor · platform</title></svelte:head>

<div class="grid h-dvh w-full grid-rows-[auto_1fr] overflow-hidden bg-background">
	<Menubar>
		{#snippet partnerLogo()}
			<span class="text-xs text-muted-foreground">Omega AURSAD Monitor</span>
		{/snippet}
		<span class="hidden font-mono text-xs text-muted-foreground lg:inline">
			{s.agent?.window ? `window ${s.agent.window}` : ''}
		</span>
		<Badge variant="status" class={tone}>
			{phase === 'running' ? 'platform · serving' : phase}
		</Badge>
	</Menubar>

	<div class="grid min-h-0 grid-cols-1 lg:grid-cols-2">
		<InputPanel {aursad} class="min-h-0 border-border lg:border-r" />
		<OutputPanel {aursad} bind:settingsOpen class="min-h-0 border-t border-border lg:border-t-0" />
	</div>
</div>

<SettingsDialog {aursad} bind:open={settingsOpen} />
