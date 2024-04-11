## 0.6.7 (unreleased)

- webui: specific remove rules changed to single-clicks


## 0.6.6 (2024-12-02)

- fix `post_removal_sleep_sec` logic (syntax err, sry)


## 0.6.5 (2024-11-29)

- add `post_removal_sleep_sec` config item
    
    - if set to value > 0 and also hdd_space is set to > 0, then we
      sleep/pause that amount of seconds after each & every torrent removal.
  
      this is to try and mitigate situation where one ARP invocation causes
      removal of multiple torrents, but on some seedboxes it takes some
      seconds for the HDD space to be reported as freed up. this means the
      same invocation would end up removing more torrents than _really_
      allowed by the set hdd_space config/rule.
      defaults to `-1`, i.e. feature is disabled

## 0.6.4 (2024-10-16)

- drone: change version-tag-changelog step image to python:3-bookworm
- allow for easily building against different python versions
- make `periodic_scan()` async

