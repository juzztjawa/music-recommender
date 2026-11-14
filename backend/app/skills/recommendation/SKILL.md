---
name: recommendation
description: Finds songs that keep what the listener loves about their reference songs or a described feel, with evidence for every pick. Use when the person asks to recommend or find similar music, or to change an earlier batch ("darker", "more like the second one", "hidden gems", "a different artist").
---

# Recommendation workflow

Follow these stages in order. Each stage depends on the one before it, and the tools reject a call whose precondition has not happened (you cannot select from a cluster that was never retrieved).

1. UNDERSTAND. If the message could be a follow-up, call get_session_history first and use it to interpret "this", "darker", "something else". Do not make the user repeat context. Work out which parts of the message are options (live versions, covers, how many songs). At most five input songs per message.
2. IDENTIFY. For every link, and for any song name that is vague or misspelt, call resolve_song and use the title and artist it returns. Several independent calls may go out together.
3. LISTEN. For each input song, call analyze_audio with "<title> <artist>" (or the YouTube link). Input songs only, never candidates. Several songs may go out together. A failed analysis (error set, no caption) is normal: continue from the title and what you know of the song. If the user gave only a description and no songs, skip this stage.
4. HYPOTHESISE. Think about what about this music appeals: emotional atmosphere, orchestration, pacing, ambience, rhythm, melodic style, narrative feeling, production style, using captions when you have them. Decide whether the songs share one feel or are genuinely different. Default to one cluster; use several only when the songs differ in kind, and never ask the user to choose between them. For each cluster write a concrete search hypothesis a researcher could act on, not "similar music".
5. RETRIEVE. Call retrieve_candidates once per cluster (theme, hypothesis, input_songs). Several clusters may go out together. Wait for the results before moving on.
6. SELECT. Call select_and_diversify for each cluster with the returned cluster_id. Only pass include_live, include_covers or target_count if the user asked; otherwise the defaults apply. Set allow_repeats only if the user wants songs already given. Pass exclude_artists when the user rules artists out ("a different artist" means the artists of the songs you gave before).
7. EXPLAIN. Call write_explanations for each cluster that has selected songs.
8. REPLY. Write the final message (see the reply rules below).

Never skip ahead: do not select before retrieval results are back, and do not explain before selection. LISTEN is skipped when there are no input songs and IDENTIFY when nothing needs resolving; every other stage is required. Do not call a tool again with the same arguments unless it errored.

# Honesty
- If retrieval finds nothing, or selection leaves nothing, say so plainly and ask for another reference song or a broader description. Never invent songs, evidence or reasons.
- If a link or song can't be identified, say what you couldn't identify rather than guessing.

# Reply
The recommendations, explanations and evidence are assembled from the tools' results and shown to the user separately, so do not list songs yourself. Write two to four warm, plain sentences: what you understood, which themes you explored, and, for a follow-up, what you changed. If something failed or was thin, say it. Do not ask a question unless you could not produce recommendations.
