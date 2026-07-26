# Why Broomarr asks Sonarr instead of the media server

Broomarr exists because of one gap that every rule-based library cleaner shares, and because of one property of rule engines that turns that gap into deleted files.

## The gap: the media server only knows what was downloaded

The natural way to decide whether a show can go is to ask the media server "has this user watched every episode?" Plex, Jellyfin and Emby all answer that question, and every cleanup tool built on top of them uses the answer.

The answer is not to the question you asked. The media server enumerates the episodes in its own library and checks watch state for each. Episodes that exist in the world but were never downloaded do not appear in that enumeration, so they cannot fail the check. "Watched every episode" actually means "watched every episode currently present."

The consequence is specific and severe. A series where an early season was never fetched reports as fully watched the moment somebody finishes a later season. It looks like a completed show by every available signal, and deleting it destroys a series that person is midway through - the precise outcome the tool was installed to prevent. This is not a rare edge: partial libraries are the normal state of any long-running setup.

Sonarr is the only component in the chain that knows the true episode list, because it fetches from TVDB and tracks each episode independently of whether a file exists. So this is a data-source problem, not an application problem. No amount of extra rules in a tool that asks the media server can recover information the media server does not have.

## The second trap: counts carry filters you did not choose

Having decided to ask Sonarr, the obvious next move is to compare its own numbers. Sonarr publishes `statistics.episodeCount` (episodes aired) and `statistics.episodeFileCount` (episodes on disk) per series. If they are equal, nothing is missing.

They can be equal and something can still be missing, because **`episodeCount` excludes unmonitored episodes.** An entire unmonitored season is invisible to both numbers at once. Two fields agreeing looks like corroboration and is not, when the same hidden filter applies to each.

There is a real case in the fixtures: a fourteen-episode series where both fields read 6, both agreed, and all eight episodes of season 1 had never been downloaded.

So Broomarr enumerates. It calls `/api/v3/episode?seriesId=N`, walks the list, and classifies each episode itself. An episode counts as missing when it has aired and has no file, **regardless of whether it is monitored** - an unmonitored episode is one Sonarr will never fetch, which makes it more permanently unwatchable, not less.

Two adjustments make enumeration usable in practice:

- **Season 0 is ignored.** TVDB puts extras, behind-the-scenes clips and specials there, and nobody downloads them. Counting them makes every complete series look permanently incomplete, which trains the operator to ignore the warning entirely - a safety check that cries wolf is worse than no check.
- **A cheap prefilter runs first.** Enumerating every series in a large library is a request per show. The cheap pass uses the counts, is deliberately permissive (it may pass shows that should block, and never blocks one that should pass), and only its survivors get the strict per-episode check. Fast and correct, in that order of discovery but not of priority.

## The property that makes rules dangerous: skip-on-unknown

Rule engines commonly evaluate a rule by removing items whose comparison returns false. When a value cannot be resolved - the service is down, the field is null, the item has no history - there is nothing to compare, so the item is skipped and stays in the working set.

That is the correct behaviour for a filter and the wrong behaviour for a safety check. A condition like "last viewed before 90 days ago" exists to remove recently-watched shows from the deletion set. If the timestamp is unavailable, skipping the rule means the show is not removed, so the check has silently stopped protecting while the configuration still reads as correct. Nothing in the interface indicates the difference between "this rule ran and passed" and "this rule could not run."

Every such failure biases the same way: towards deleting more. None of them can cause a missed deletion, only an unwanted one, and the two outcomes are not symmetric. A show that should have been deleted and was not costs disk space. A show that should not have been deleted and was is gone.

Broomarr inverts this. Every branch that cannot establish a fact returns a reason to block: no history at all, the watcher absent from the history, no last-view timestamp, an exception reading the episode list. There is no path through the logic where an unknown value results in a pass.

## Why it cannot delete

Broomarr makes no write calls and touches no files. It is not a limitation to be lifted later - it is the property that makes the rest tolerable.

A tool with the power to delete has to be right every time it runs, including runs nobody watched, runs after a service outage, and runs after a config change somebody made six weeks ago. A tool that only prints a list has to be right only in the moment somebody reads the list and acts on it, with the full reasoning in front of them. The second bar is achievable; the first is not, for a decision this asymmetric.

Deletion stays a deliberate manual action in Sonarr. That is the design, not a milestone.
