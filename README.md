AutoRemovePlus
==============

AutoRemovePlus is a plugin for [Deluge v2.x](http://deluge-torrent.org) that
you can use to automatically remove torrents. It's
based on AutoRemove 0.1 by Jamie Lennox.

Other forks from v1 that support Deluge v2:
- https://github.com/springjools/deluge-autoremoveplus - note this one has working gtk3 ui (actually not sure)
- https://github.com/tote94/deluge-autoremoveplus - think this is only webui (actually not sure); [this](https://github.com/springjools/deluge-autoremoveplus/issues/36#issuecomment-830783002) refers
it's _not_ springjools that has the working GTKui prefs page;

For Deluge v1 support, see [deluge-1 branch](https://github.com/laur89/deluge-autoremoveplus/tree/deluge-1)

This is a GtkUI and WebUI plugin.

Features
--------
- Select how many torrents are allowed at the same time.
- Choose to remove or pause them based on multiple criteria age, seeders, seed time or ratio.
- Set specific removal rules depending on tracker or LabelPlus label.
- Remove only torrents from specific trackers or LabelPlus labels.
- Only remove torrents if under a certain HDD space threshold.
- Select if torrents have to fulfill both or either criteria.
- Delete torrents in order (e.g. delete torrents with highest ratio first).
- Don't remove torrents if they don't reach a minimum time (in days) or ratio.
- Choose the removal interval.
- Right click and select torrents that you don't want automatically removed.
- Remove torrent data option.
- Create an exempted tracker or LabelPlus label list, so that torrents that belong to those trackers or labels are not removed.
- Fully functional WebUI.  

Usage
-----
Look for torrents to remove every hour:

> Check every: 1

Remove every torrent that meets minimum criteria:

> Maximum torrents: 0

Don't remove torrents unless Deluge has over 500:

> Maximum torrents: 500

Delete torrents even if HDD space not under minimum:

> Minimum HDD space: -1

Only remove torrents when the main HDD has less than 10 GB free:

> Minimum HDD space: 10

Remove torrents that have a ratio over 2.0 and have been seeding for at least 2 days:

> Remove by: Ratio, Min: 2.0, and, Remove by: Seed Time, Min: 48

Remove torrents that have a ratio over 2.0 or have been seeding for at least 10 hours:

> Remove by: Ratio, Min: 2.0, or, Remove by: Seed Time, Min: 10

Remove torrents that have a ratio over 2.2 and were added at least 4 days ago:

> Remove by: Ratio, Min: 2.2, or, Remove by: Age in days, Min: 4

Remove torrents only according to first criteria:

> :black_small_square: Second Remove by: criteria

Pause torrents instead of removing them:

> :black_small_square: Remove torrents

The rest of the options are pretty self explanatory

Development
-----------
- use python 3
- virutal env manager `virtualenv`
- run:

```
+ Install python 3.7  (or whatever your seedbox uses for python3; any py3 version should be ok)
- first install pyenv:
  $ curl -L https://github.com/pyenv/pyenv-installer/raw/master/bin/pyenv-installer | bash
- install py3:  $ pyenv install 3.9.7
- cd to project root and change to version:  $ pyenv local 3.9.7
  - this will create .python-version file at the root
- verify your py version: $ python --version

+ Setup virtenv; either
A) manually... (not recommended):
- install virtualenv:  $ pip install virtualenv
- create venv:  $ python -m virtualenv env  (note 'env' specifies the name/location to create
  the virtual environment in)
- activate env:  $ source env/bin/activate
- to switch projects or just leave the venv, run:  $ deactivate
B) ...or using pyenv (recommended):
- this step might still be needed, unsure:  install virtualenv:  $ pip install virtualenv
- create venv:  $ pyenv virtualenv venv39  (again, 'venv39' is just the name/location of the env)
- switch to said env:  $ pyenv local venv39  (modifies project's .python-version file)
- if you have [eval "$(pyenv virtualenv-init -)"] in your .bashrc, then
  env activation/deactivation should be automatic; to do it manually, then
    pyenv activate <name>
    pyenv deactivate
```

Building
--------

Building uses Docker to easily swap out Python versions. Note that if you're running an older version of Docker you may need to enable BuildKit manually.

Run:

```
make build
```

By default Python 3.11 is used. If you wish to target a different version specify it as an environment variable:

```
make build PYTHON_VERSION=3.10
```

The resulting `AutoRemovePlus-vX.Y.Z.egg` file can be found in the `/dist` directory.
Note the .egg doesn't contain python version in the filename - our modified
`setup.py` has logic that renames the generated .egg.

Roadmap/TODO
------------

- similar to `TotalTraffic` plugin, start tracking upload bandwidth, but _per
  torrent_. Idea is to enable rule to only remove torrents that have uploaded
  less than X amount in past Y time period. So removal rule should be something like

```
if (ratio > 1 || seed_time > 7days) && t.recent_upload < X:
    t.remove

TODO: how would recent_upload be defined? guess we want it to represent
something like [KiB in past 1h]. Both data amount & time period need to
be configurable.

We likely want to keep current torrent data in-memory, and write it down
periodically to `autoremoveplusstates.conf`; again, sort of similar what
TotalTraffic is doing.
```
This removes the impossible target ratio definition - we should just set the
_minimum_ ratio & seed time rules, and let the active torrents upload however
long they can.
Additional problem will be incorporating it with our UI though.

- as previously, but perhaps also allow measuring avg speed:
```
avg_upload_speed = torrent['total_uploaded'] / torrent['active_time'] if torrent['active_time'] > 0 else 0
  OR don't count the upload speed for the time we were downloading ourselves. unsure why we shouldn't tho...:
avg_upload_speed = torrent['total_uploaded'] / torrent['seeding_time'] if torrent['seeding_time'] > 0 else 0
```

- need to add possibility to count seeding time from the moment torrent hits 100%;
  eg TL writes this [in their wiki](þtp://wiki.torrentleech.org/doku.php/hnr):
  > Be aware that seeding time only counts for fully completed torrents (downloaded 100%).

  We might be able to use torrent attributes `last_seen_complete` and/or `finished_time`;
  note springjool's core.py has `_time_seen_complete()` that might be what we need.
  Thinking about it more, think finished_time attr fits our use-case better. Or maybe
  `seeding_time`? see libtorrent explanation on fields [here](https://www.libtorrent.org/reference-Add_Torrent.html)
  TODO: this all is likely already covered by the existing func_seed_time we're
  even using in production!
- items should be removed from our state file via Execute plugin on torrent removal
  event; otherwise torrents removed outside of this script would not get removed
  from the state tracker. maybe there's some deluge's removed event we could tap
  into? OR: include some cleanup logic in the plugin itself to remove state info
  for torrents that are no longer around, ie they had to be removed by some other means.
- according to [this post](https://forum.deluge-torrent.org/viewtopic.php?p=233390#p233390),
  torrmanager.get_status() can accept `update=True` param not to return cached results.
  this makes no sense for static fields such as name or size, but might be needed for
  `seed_time`, `ratio`...; apparently one of the forks of plugin has removed the caching.
- add rules/support to handle torrents such as

```
Name: torrent-name.mkv
ID: bcbcc09416b8756384f9d72b9dd3cd0762279527
State: Downloading Down Speed: 0.0 K/s Up Speed: 0.0 K/s
Seeds: 0 (0) Peers: 4 (15) Availability: 0.08 Seed Rank: -
Size: 45.0 M/532.6 M Downloaded: 44.7 M Uploaded: 0 B Share Ratio: 0.00
ETA: - Seeding: - Active: 16h 20m
Last Transfer: 16h 17m Complete Seen: Never
Tracker: tracker.org
Tracker status: Announce OK
Progress: 8.45% [#####-------------------------------------------------------]
Download Folder: /home/myuser/files/

Name: torrent-name-2
ID: aba61c7f8068c5b5a6414k39cec41d04477f7a4a
State: Downloading Down Speed: 0.0 K/s Up Speed: 0.0 K/s
Seeds: 0 (0) Peers: 0 (7) Availability: 0.00 Seed Rank: -
Size: 0 B/445.1 M Downloaded: 0 B Uploaded: 0 B Share Ratio: -1.00
ETA: - Seeding: - Active: 16h 21m
Last Transfer: ∞ Complete Seen: Never
Tracker: tracker.org
Tracker status: Announce OK
Progress: 0.00% [------------------------------------------------------------]
Download Folder: /home/myuser/files/incomplete
```
note the `Complete Seen` & `Availability` values.


Workarounds
-----------

If after building the egg file, the plugin does not load in Deluge:

- Delete the `AutoRemovePlus-vX.Y.Z.egg` in `/deluge/plugins` directory.
- Delete the `AutoRemovePlus.conf` files.
- Restart Deluge.

See also
--------

- https://github.com/l3uddz/tqm - go-based torrent removal program
- https://github.com/jerrymakesjelly/autoremove-torrents
- springjools fork thread is think [this one](https://forum.deluge-torrent.org/viewtopic.php?f=9&t=47243&p=233391&hilit=springjools+fork#p233391)
- [this post](https://forum.deluge-torrent.org/viewtopic.php?p=233889#p233889) contains
  Execute plugin that emits 4th param - LabelPlus label - to scripts
- for deluge2 LabelPlus plugin, guess we need to grab mhertz' [hack](https://forum.deluge-torrent.org/viewtopic.php?p=233889#p233889)?

