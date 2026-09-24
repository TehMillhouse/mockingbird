# Mockingbird retrospective and idea backlog

A record of how the level-generation backend got to its current shape: which problems
showed up, which ideas were considered, and which of them were dropped, tried without
success, or adopted. The second half lists ideas that were never tried, with enough
detail to pick them up later.

Legend: ❌ dropped or not pursued · ☑️👎 tried, did not help · ☑️👍 tried, helped or
became part of the design.

## 1. Initial design

Problem: nothing existed. Requirements: singable melodies in a requested key, meter,
voice and difficulty, with a minimal accompaniment, in a format no frontend depends on.

- ☑️👍 Transpose every melody to a C-major / A-minor frame; absolute MIDI pitch tokens,
  duration tokens on a 24-ticks-per-quarter grid, explicit `BAR`, `TIE` for notes that
  would cross a bar line. The key tonic is applied on export, never tokenised.
- ❌ Scale-degree tokens (need accidental tokens, ambiguous minor sixth/seventh),
  interval tokens (tonal centre and range become unobservable), position-in-bar tokens
  (double the sequence length; duration + `BAR` lets the sampler verify bar fill).
- ❌ Learning chords jointly with the melody (only Nottingham had chord symbols).
  ☑️👍 Rule-based Viterbi harmonizer after generation instead.
- ❌ LSTM baseline, Nottingham and The Session corpora, OpenSheetMusicDisplay.
- ☑️👍 Corpora: Essen (European files only), Bach chorale sopranos, Palestrina /
  Monteverdi / Josquin top voices from the music21 corpus.
- ☑️👍 Key detection from the final of the lowest voice (or the melody final for
  monophonic tunes), mode from the third above it. Modal pieces land in the nearest
  major/minor frame with their characteristic degrees as accidentals.
- ☑️👍 Internal level JSON, exporters to ABC, MusicXML and MIDI; abcjs preview page as a
  development tool only.
- Owner decisions that stuck: train on windows of up to 32 bars and truncate; ignore
  fermatas as notation (they came back as phrase markers); no cadence engineering
  (reversed later, see section 5).

## 2. First listening pass

Problems: wrong clefs, tenor sounding an octave low, ABAB repetition for whole levels,
`block` and `arpeggio` accompaniment sounding identical.

- ☑️👍 Bass clef for basses, octave-transposing treble clef for tenors; the ABC writer
  writes tenor pitches an octave up because abcjs plays `treble-8` an octave down.
- ☑️👍 Bar-repeat cap in the sampler: a bar identical to one already sampled twice
  cannot be completed again. Largely superseded by phrase tokens later.
- ☑️👍 Accompaniment written as a second ABC voice on a bass-clef staff; abcjs's own
  chord playback switched off. Same accompaniment in ABC, MusicXML and MIDI.
- ☑️👍 Separate voice and piano volume by scaling MIDI velocities per track before
  synthesis (abcjs has no per-voice volume).

## 3. Endings

Problem: phrases stopped rather than ended; typical failure a half note followed by a
run of sixteenths.

- ☑️👎 A single `FINAL` marker before the last bar: too little warning to prepare a
  cadence, the penultimate bar is already written when it arrives.
- ☑️ Reject candidates whose final bar's longest note is not its last note: small,
  kept, does nothing for pitch.
- ☑️👍 Countdown tokens `REMAIN_4 … REMAIN_1` opening the last four bars of every
  window that really contains the source piece's ending, forced at generation. Tonic
  endings rose from about 62% to 94% (folk) in one step. Harmonizer biased towards
  pre-dominant / dominant / tonic over the last bars.

## 4. Data expansion

- ☑️👍 OpenScore Lieder read directly from MuseScore files with ms3 (pandas must stay
  below 3; MuseScore 2 files are skipped).
- ❌ Meertens Tune Collections (registration form, non-commercial licence, folk already
  dominant), KernScores scraping (small vocal collections).
- ☑️👍 PDMX vocal subset: lyrics present, no licence conflict, deduplicated, classical or
  religious genre; about 17,000 scores tagged `choral`. Vocal part chosen as the highest
  part carrying lyrics. Corpus grew from 13k to 42k windows.

## 5. Architecture

Question: positional encoding, model size, weight sharing.

- ☑️👍 Metric embeddings (bar index and tick within the bar added to each token):
  same likelihood, faster convergence, cleaner endings. Default since then.
- ☑️👎 Rotary embeddings over token index: slightly worse than learned positions.
- ☑️ Metric RoPE (rotation by musical time; eight frequency bands locked to eighth,
  beat, bar and multiples of the bar): about 0.01 nats better likelihood, apparently
  fewer tonic endings. ☑️👎 Distance-free "anchored" attention to the prefix did not
  change the endings. The ending gap was later judged to be within seed noise
  (two seeds of the same model differed by 9 points). Adopted as production once the
  cadence signal came from annotation (section 6).
- ☑️👍 Looped stack (prelude, shared core block pair run three times with a learned
  per-pass embedding, coda, sandwich norm): matches the 5M-parameter stack at 36% of the
  weights and beats a same-size plain stack by 0.022 nats. It trains longer before its
  curve flattens but has not exceeded the big model.
- Open: an overnight run compares the production stack, the looped model and a
  384-wide stack on long schedules (`models/overnight/chain.log`) to see where the
  curves converge and whether the 5M model is undersized. No run so far has shown
  overfitting; train loss stays above validation under dropout 0.2.

## 6. Cadences as training signal

Owner's thesis: if cadences only worked with the weaker positional encoding, fix the
cadence training signal rather than weaken time-keeping, the way one would annotate
phrase structure to make it learnable.

- ☑️👍 Phrase boundaries from every source: Essen line breaks parsed from the raw ABC
  text (music21 drops them), fermatas, lyric punctuation, double bar lines, rests of at
  least a beat. `PHRASE_END_IN_k` opens each of the last four bars before a phrase end,
  `CAD_<label>` opens the bar containing it. Generation takes a phrase plan (bars per
  phrase, cadence per phrase). Tonic endings 66% → 99%; requested half cadences matched
  about 70%, perfect authentic about 80%; ABAB' phrase structure appeared unprompted.
- ☑️👍 Label refinement: `SUB` class for subdominant endings, raised sixth and seventh
  recognised as degrees in minor, applied dominants classed as half cadences, canonical
  phrase ends (never after a rest, at least two notes and two beats). `OTHER` fell from
  32% to 9% of labels.
- ❌ Form-letter annotation (A, B, A', C) for phrase structure: obsolete, the phrase
  tokens produced the structure by themselves.

## 7. Accompaniment

Problem: harmonically fine but "cookie-cutter": root-position triads, jumping bass, one
texture, chord changes every half bar regardless of the melody.

- ☑️👍 Chords fitted per beat with a change cost that is small on strong beats and
  large on weak ones; three lower voices voice-led by a second Viterbi pass (smooth
  inner motion, bass by step or contrary, parallel fifths and octaves penalised,
  complete chords, cadential six-four); textures per style (chorale re-attacks with the
  melody, oompah for folk, broken eighths for lied). Voicing happens in concert pitch
  after the melody is placed in the singer's range.
- ❌ (deferred) Learned harmonization, see backlog.

## 8. Evaluation and process

- ☑️👍 Blind side-by-side listening page; the owner's judgement agreed with the metrics
  where the metrics were trustworthy.
- ☑️ Cadence metric (tonic ending, stable ending, final note longest, dominant
  preparation): catches 30-point effects, cannot rank models closer than about 10
  points because training seeds alone move it by 9. Multiple seeds, not more samples,
  are the remedy.
- ☑️👍 Compliance metric (requested versus realised cadence per phrase), convergence
  charts, per-run comparison table.
- Lesson: read the per-epoch tables before interpreting a curve. Two claims from chart
  reading were wrong and corrected by the numbers.

## Idea backlog

Ideas not tried, with the problem each addresses. Ordered roughly by expected value.

### Learned SATB harmonization (backing singer)
Problem: the rule-based accompaniment is correct but generic, and the planned backing
singer needs an idiomatic vocal line, not a keyboard texture. The corpus now holds
about 8,000 SATB choral scores plus the Bach chorales with all voices aligned. Idea: a
second model conditioned on the melody that emits alto, tenor and bass lines, either
as interleaved per-beat voice tokens or as three parallel streams, sampled under
consonance, range and no-crossing constraints. The rule-based harmonizer stays as the
fallback texture and as the labeling tool. Two to three days of work.

### Multi-seed evaluation protocol
Problem: the cadence metric's run-to-run variance (about 9 points) swamps any difference
under 10 points, and likelihood differences of 0.01 nats have never been shown to be
audible. Idea: for any architecture decision, train three seeds per variant and report
mean and spread of both metrics; treat a difference as real only when the spreads do
not overlap. Costs three times the GPU time per variant, which is why it has not been
done; it is the only way to settle questions like metric RoPE versus learned positions.

### Classifier-free guidance on conditioning tokens
Problem: cadence compliance sits at 70 to 80%; difficulty and style conditioning are
similarly soft. Idea: train with the prefix and cadence tokens randomly replaced by a
null token some of the time, then at sampling combine conditional and unconditional
logits with a guidance weight above one. Standard in image and audio models, cheap
to add, and it turns every existing conditioning token into a dial. Would need a
check that guidance does not push melodies out of range or into repetition.

### Phrase-level descriptor tokens
Generalises the lesson of sections 3 and 6: anything we want to control should be
annotated. Candidates derivable from the data: phrase range (narrow, medium, wide),
contour (arch, ascending, descending, static), rhythmic density, presence of a leap.
Problem solved: difficulty is currently a single bucket calibrated to style quintiles,
which is not how a choir director thinks about an exercise ("stepwise, one octave,
quarters and eighths"). Descriptor tokens would let the trainer request exactly that.

### Difficulty as pedagogical tiers
Related to the above: replace or complement the quintile buckets with absolute tiers
defined by interval classes allowed, range, rhythmic vocabulary and chromaticism,
so that "level 3" means the same thing across styles. The sampler already enforces
leap and span caps per level; the missing part is training-time labels on the same
scale so the model produces idiomatic level-3 melodies rather than clipped level-5
ones.

### Adaptive loop count at inference
The looped model degrades gracefully around its training centre (1 pass 0.892, 2
passes 0.855, 3 passes 0.852, 4 passes 0.854 on the small corpus). Idea: train with a
wider jitter and choose the pass count per level at inference, trading latency for
quality, or stop looping when the representation stops changing. Interesting rather
than needed; the current latency is about two seconds per level.

### Reversed-sequence training
Alternative route to good endings: train on melodies reversed in time so the cadence
is the well-conditioned start of generation, then reverse the output. Made obsolete by
the phrase tokens, kept here because it is a general trick for any "the end matters
most" sequence problem.

### Geometric-only metric RoPE
Diagnostic, not improvement: keep rotation by musical time but drop the eight
meter-locked bands. Tells whether the bar-periodic bands were behind the earlier ending
gap (which may have been noise). Only worth running inside a multi-seed protocol.

### Relative attention (Music Transformer style)
Problem it targets: motif and phrase repetition with variation. The phrase tokens
already produce ABAB' structure, so this is now a refinement. More code and slower
attention than any positional scheme tried so far.

### Pickup bars at generation
Training data has pickups (most Essen tunes); generation never produces one because
the constraint state starts at a bar line. Adding a pickup option (length in beats,
`PICKUP` token in the prefix, countdown and phrase logic aware of the shifted bar
grid) would make levels look like real repertoire. Small but fiddly.

### More classical vocal data
Meertens (18k Dutch folk songs, `**kern`, needs a registration form, CC BY-NC-SA) if
folk ever needs more; Josquin Research Project (about 1,200 Renaissance works) if the
renaissance style is wanted; CPDL for choral music if a MusicXML harvesting pipeline
is written. PDMX also has about 6,000 more vocal scores in genres other than
classical and religious that were filtered out.

### Frontend prerequisites learnt here
The melody and accompaniment must be two separately gained audio sources so the mix
changes live (the preview re-primes the synth instead); the level JSON already carries
both. Clefs by voice and the tenor octave convention must be honoured by whatever
renders notation. Keybinds for play, pause, restart, tempo and the two volumes exist in
the preview and can be carried over.
