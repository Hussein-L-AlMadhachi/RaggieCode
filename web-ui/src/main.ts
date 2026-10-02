import { mount } from 'svelte'
import './app.css'
import App from './App.svelte'
import { isVsCodeHost, onHostMessage } from './lib/bridge'
import { chatStore } from './lib/store.svelte'

// Hosted layout mode: CSS keyed off html.vscode-host sizes the app to fill
// the webview iframe exactly (see app.css), avoiding 100vw/100vh scrollbar
// drift that offsets the app in a narrow VS Code panel.
if (isVsCodeHost()) {
  document.documentElement.classList.add('vscode-host')
}

// Host-injected actions (VS Code extension host). onHostMessage is a no-op
// outside a VS Code webview, so the standalone app is unaffected.
onHostMessage((msg) => {
  if (msg.type === 'raggie-prompt' && typeof msg.text === 'string') {
    // send() reads the draft, clears it, and streams the turn   the same
    // flow as a manual submit. Focus the composer like insertCommand does.
    chatStore.draft = msg.text;
    chatStore.composerFocus++;
    void chatStore.send();
  } else if (msg.type === 'raggie-open-setup') {
    void chatStore.openSetup();
  }
})

const app = mount(App, {
  target: document.getElementById('app')!,
})

export default app
