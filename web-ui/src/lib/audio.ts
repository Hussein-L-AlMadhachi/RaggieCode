const audio_ctx = new AudioContext();


/** One short glass clink: the "turn finished" cue. */
export function playClink() {
    const gain = audio_ctx.createGain();
    gain.gain.setValueAtTime(0.1, audio_ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audio_ctx.currentTime + 0.4);
    gain.connect(audio_ctx.destination);

    const osc = audio_ctx.createOscillator();
    osc.frequency.value = 2000;
    osc.connect(gain);

    // A second voice a few Hz off adds a slight shimmer, like a real rim.
    const shimmer = audio_ctx.createOscillator();
    shimmer.frequency.value = 2003;
    shimmer.connect(gain);

    osc.start();
    shimmer.start();
    osc.stop(audio_ctx.currentTime + 0.4);
    shimmer.stop(audio_ctx.currentTime + 0.4);
}


/** Three clinks in a row: the "needs your input" cue for prompts. */
export function playAttentionClink() {
    playClink()
    setTimeout( playClink, 230 )
    setTimeout( playClink, 460 )
}
