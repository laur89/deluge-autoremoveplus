#
# core.py
#
# Copyright (C) 2014-2016 Omar Alvarez <osurfer3@hotmail.com>
# Copyright (C) 2011 Jamie Lennox <jamielennox@gmail.com>
#
# Basic plugin template created by:
# Copyright (C) 2008 Martijn Voncken <mvoncken@gmail.com>
# Copyright (C) 2007-2009 Andrew Resch <andrewresch@gmail.com>
# Copyright (C) 2009 Damien Churchill <damoxc@gmail.com>
#
# Deluge is free software.
#
# You may redistribute it and/or modify it under the terms of the
# GNU General Public License, as published by the Free Software
# Foundation; either version 3 of the License, or (at your option)
# any later version.
#
# deluge is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with deluge.    If not, write to:
#   The Free Software Foundation, Inc.,
#   51 Franklin Street, Fifth Floor
#   Boston, MA  02110-1301, USA.
#
#    In addition, as a special exception, the copyright holders give
#    permission to link the code of portions of this program with the OpenSSL
#    library.
#    You must obey the GNU General Public License in all respects for all of
#    the code used other than OpenSSL. If you modify file(s) with this
#    exception, you may extend this exception to your version of the file(s),
#    but you are not obligated to do so. If you do not wish to do so, delete
#    this exception statement from your version. If you delete this exception
#    statement from all source files in the program, then also delete it here.
#

import logging
from deluge.plugins.pluginbase import CorePluginBase
import deluge.component as component
import deluge.configmanager
from deluge.core.rpcserver import export

from twisted.internet import reactor, threads
from twisted.internet.task import LoopingCall, deferLater
from twisted.internet.defer import ensureDeferred
from deluge._libtorrent import lt
import functools
import os
import subprocess
import time

log = logging.getLogger(__name__)


# from https://stackoverflow.com/a/44627140/1803648
def ensure_deferred(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        result = f(*args, **kwargs)
        return ensureDeferred(result)
    return wrapper


DEFAULT_PREFS = {
    'max_seeds': 0,
    'filter': 'func_ratio',
    'filter2': 'func_added',
    'count_exempt': False,
    'remove_data': False,
    'labelplus': False,
    'trackers': [],
    'labels': [],
    'min': 0.0,
    'min2': 0.0,
    'hdd_space': -1.0,
    'use_quota_for_free_space': False,
    'quota_executable': '/usr/bin/quota',
    'interval': 0.5,  # hours
    'sel_func': 'and',
    'force_reannounce_before_remove': False,
    'reannounce_max_wait_sec': 20,
    'skip_removal_on_reannounce_failure': True,
    'remove': True,
    'post_removal_sleep_sec': -1.0,
    'enabled': False,
    'tracker_rules': {},
    'label_rules': {},
    'rule_1_enabled': True,
    'rule_2_enabled': True
}


def _get_ratio(i_t):
    return i_t[1].get_ratio()


def _time_last_transfer(i_t):
    (i, t) = i_t
    try:
        # time since last transfer (upload/download) in hours
        time_since_last_transfer = round(t.get_status(['time_since_transfer'], update=True)['time_since_transfer'] / 3600.0, 4)
    except Exception as e:
        log.error("Unable to get torrent property: {}".format(e))
        return False

    return time_since_last_transfer


def _age_in_days(i_t):
    now = time.time()
    added = i_t[1].get_status(['time_added'])['time_added']
    log.debug("_age_in_days(): Now = {}, added = {}".format(now, added))
    age_in_days = round((now - added) / 86400.0, 4)
    log.debug("_age_in_days(): Returning age: [{} days]".format(age_in_days))
    return age_in_days


def _time_since_seen_complete(i_t):
    (i, t) = i_t
    now = time.time()
    try:
        seen_complete = t.get_status(['last_seen_complete'], update=True)['last_seen_complete']
    except Exception as e:
        log.error("Unable to get torrent property: {}".format(e))
        return False

    if not seen_complete: return False  # TODO: is this ok? default value think is 0, which would then cause us to return False

    log.debug("Seen complete on: {}, now = {}".format(seen_complete, now))
    time_last_seen_complete = round((now - seen_complete) / 3600.0, 4)  # time in hours
    log.debug("Returning time since seen complete: {}".format(time_last_seen_complete))
    return time_last_seen_complete


def _get_free_space_quota(quota_exe_path):
    if not os.path.isfile(quota_exe_path):
        raise Exception('[{}] not found'.format(quota_exe_path))

    quota_proc = subprocess.Popen([quota_exe_path, '--no-wrap', '--hide-device'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    q_out, q_err = quota_proc.communicate()
    if quota_proc.returncode != 0 or len(q_err) > 0:
        raise Exception('quota exited w/ {}'.format(quota_proc.returncode))

    q_out = q_out.splitlines()[2].split()  # take 3rd line and split it up
    free = (int(q_out[2]) - int(q_out[0])) / 976563  # hard_limit - used; note we convert KiB to GB
    return free  # free quota, in GB


def _get_seed_time(i_t):
    st = round(i_t[1].get_status(['seeding_time'], update=True)['seeding_time'] / 3600.0, 4)
    log.debug("_get_seed_time(): %s hours", st)
    return st


# Add key label also to get_remove_rules():
filter_funcs = {
    'func_ratio': _get_ratio,
    #'func_added': lambda i_t: round((time.time() - i_t[1].get_status(['time_added'])['time_added']) / 86400.0, 4),
    'func_added': _age_in_days,
    'func_seed_time': _get_seed_time,
    'func_seeders': lambda i_t: i_t[1].get_status(['total_seeds'], update=True)['total_seeds'],
    'func_availability': lambda i_t: i_t[1].get_status(['distributed_copies'], update=True)['distributed_copies'],  # above 1, at least 1 peer has a full copy; think this only has meaning when state='Downloading'; when Seeding, it's always 0! see https://forum.deluge-torrent.org/viewtopic.php?p=233084#p233084
    'func_time_since_transfer': _time_last_transfer,
    'func_time_seen_complete': _time_since_seen_complete,
    'func_state': lambda i_t: i_t[1].get_status(['state'], update=True)['state'].lower(),  # [downloading, paused, seeding, error, moving, queued, checking, allocating] (note all lower case!)
    'func_progress': lambda i_t: i_t[1].get_status(['progress'], update=True)['progress']  # float, 0-100; note it also reports 100 if state = Error; see ~ https://git.deluge-torrent.org/deluge/tree/deluge/core/torrent.py#n972
}
# other potentially useful statuses:
# - total_done: (taken  directly from libtorrent); total # of bytes of the files(s) that we have; unsure if or how the value changes when torrent state changes from Downloading to {Seeding,Moving...}


sel_funcs = {
    'and': lambda a_b: a_b[0] and a_b[1],
    'or': lambda a_b: a_b[0] or a_b[1],
    'xor': lambda a_b: (not a_b[0]) ^ (not a_b[1])
}


class Core(CorePluginBase):

    def enable(self):
        log.debug("AutoRemovePlus: Enabled")

        self.config = deluge.configmanager.ConfigManager(
            "autoremoveplus.conf",
            DEFAULT_PREFS
        )
        self.torrent_states = deluge.configmanager.ConfigManager(
            "autoremoveplusstates.conf",
            {}
        )

        # Safe after loading to have a default configuration if no gtkui
        self.config.save()
        self.torrent_states.save()

        # it appears that if the plugin is enabled on boot then it is called
        # before the torrents are properly loaded and so periodic_scan() receives an
        # empty list. So we must listen to SessionStarted for when deluge boots
        #  but we still have apply_now so that if the plugin is enabled
        # mid-program periodic_scan() is still run
        self.looping_call = LoopingCall(self.periodic_scan)
        deferLater(reactor, 5, self.start_looping)
        self.torrentmanager = component.get("TorrentManager")

    def disable(self):
        if self.looping_call.running:
            self.looping_call.stop()

    def update(self):
        pass

    def start_looping(self):
        log.info('check interval loop starting')
        self.looping_call.start(self.config['interval'] * 3600.0)

    @export
    def set_config(self, config):
        """Sets the config dictionary"""
        for key in list(config.keys()):
            self.config[key] = config[key]
        self.config.save()
        if self.looping_call.running:
            self.looping_call.stop()
        self.looping_call.start(self.config['interval'] * 3600.0)

    @export
    def get_config(self):
        """Returns the config dictionary"""
        return self.config.config

    @export
    def get_remove_rules(self):
        return {
            'func_ratio': 'Ratio',
            'func_added': 'Age in days',
            'func_seed_time': 'Seed Time (h)',
            'func_seeders': 'Seeders',
            'func_availability': 'Availability',
            'func_time_since_transfer': 'Time since transfer (h)',
            'func_time_seen_complete': 'Time since seen complete (h)',
            'func_state': 'Torrent state',
            'func_progress': 'Torrent progress (0-100)'
        }

    @export
    def get_ignore(self, torrent_ids):
        if not hasattr(torrent_ids, '__iter__'):
            torrent_ids = [torrent_ids]

        return [self.torrent_states.config.get(t, False) for t in torrent_ids]

    @export
    def set_ignore(self, torrent_ids, ignore=True):
        log.debug(
            "Setting torrents %s to ignore=%s"
            % (torrent_ids, ignore)
        )

        if not hasattr(torrent_ids, '__iter__'):
            torrent_ids = [torrent_ids]

        for t in torrent_ids:
            self.torrent_states[t] = ignore

        self.torrent_states.save()

    def check_min_space(self):
        min_hdd_space = self.config['hdd_space']  # in GB
        # if deactivated delete torrents regardless of remaining free drive space:
        if min_hdd_space < 0.0:
            return False

        real_free_space = None
        if self.config['use_quota_for_free_space']:
            try:
                real_free_space = _get_free_space_quota(self.config['quota_executable'])
            except Exception as e:
                real_free_space = None
                log.warning("check_min_space(): _get_free_space_quota() threw up: %s", e)

        if real_free_space is None:
            real_free_space = component.get("Core").get_free_space() / 1073741824.0  # bytes -> GB

        log.debug("Free Space in GB (real/min.required): %s/%s" % (real_free_space, min_hdd_space))

        # if hdd space below minimum delete torrents
        if real_free_space > min_hdd_space:
            return True  # there is enough space, do not delete torrents
        else:
            return False

    def pause_torrent(self, torrent):
        try:
            torrent.pause()
            log.debug("pause_torrent(): successfully paused torrent: [%s]", torrent.torrent_id)
        except Exception as e:
            log.warning(
                    "Problems pausing torrent: [%s]: %s", torrent.torrent_id, e
            )

    # note: great hint on libtorrent force_announce inner-workings is at https://forum.deluge-torrent.org/viewtopic.php?p=230210#p230210
    def reannounce(self, tid, t, force_announce):
        # note the first two announce_* arg values are the defaults from https://libtorrent.org/reference-Torrent_Handle.html#force_reannounce()
        announce_seconds = 0    # how many seconds from now to issue the tracker announces; default = 0
        announce_trkr_idx = -1  # specifies which tracker to re-announce. If set to -1 (which is the default), all trackers are re-announced.
        announce_flags = lt.reannounce_flags_t.ignore_min_interval  # announce NOW; as discussed in https://github.com/arvidn/libtorrent/discussions/7334

        t_end = time.time() + self.config['reannounce_max_wait_sec']
        while time.time() < t_end:
            if force_announce:
                try:
                    t.handle.force_reannounce(announce_seconds, announce_trkr_idx, announce_flags)  # note libtorrent's force_reannounce() returntype is void
                    log.debug("reannounce(): forced reannounce OK for torrent [%s]", tid)
                    return True
                except Exception as e:
                    log.warning("reannounce(): Problems calling libtorrent.torr.force_reannounce(): %s", e)
            else:
                if t.force_reannounce():  # this one uses Deluge torrent function, as opposed to directly calling libtorrent's
                    log.debug("reannounce(): non-forced reannounce OK for torrent [%s]", tid)
                    return True
                else:
                    log.warning("reannounce(): non-forced reannouncing failed for torrent: [%s]", tid)
            time.sleep(5)  # TODO: make this configureable?

        log.error("reannounce(): Problems reannouncing for torrent: [%s]; giving up", tid)
        return False


    def remove_torrent(self, tid, torrent, remove_data):
        # extra logging for debugging premature torrent removal issues: {
        # seed_time = torrent.get_status(['seeding_time'], update=True)['seeding_time']
        # seed_time_h = _get_seed_time((tid, torrent))
        # log.error("remove_torrent(): pre-announce seed_time: [%s], h: [%s]", seed_time, seed_time_h)
        # }

        force_announce = self.config['force_reannounce_before_remove']

        # update trackers to make sure the latest upload amount & time are reflected
        # prior to nuking torrent.
        #
        # TODO: maybe reannounce should also be called on torrent completion event, not only prior to removal?
        if self.reannounce(tid, torrent, force_announce):
            time.sleep(2)  # not sure if needed, but let's give some time for the tracker
        else:
            if self.config['skip_removal_on_reannounce_failure']:
                log.warning(
                    "remove_torrent(): reannounce (force = %s) failed for torrent: [%s]; skipping remove", force_announce, tid)
                return False
            else:
                log.warning(
                    "remove_torrent(): reannounce (force = %s) failed for torrent: [%s]; removing regardless...", force_announce, tid)

        try:
            seed_time = torrent.get_status(['seeding_time'], update=True)['seeding_time']
            seed_time_h = _get_seed_time((tid, torrent))
            total_time_uploaded = torrent.get_status(['total_uploaded'], update=True)['total_uploaded']  # in deluge's internal status, it's under status.all_time_upload
            total_time_downloaded = torrent.get_status(['all_time_download'], update=True)['all_time_download']
            age_sec = time.time() - torrent.get_status(['time_added'])['time_added']
            # note these 2 total_time_* are in bytes, not time values:
            total_time_uploaded = torrent.get_status(['total_uploaded'], update=True)['total_uploaded']  # in deluge's internal status, it's under status.all_time_upload
            total_time_downloaded = torrent.get_status(['all_time_download'], update=True)['all_time_download']

            log.debug("remove_torrent(): removing torrent [%s]... remove_data = %s, seed_time: [%s], h: [%s], ratio: %s, age_sec: [%s], total_time_up: [%s], total_time_down: [%s]",
                      tid, remove_data, seed_time, seed_time_h, torrent.get_ratio(), age_sec, total_time_uploaded, total_time_downloaded)

            self.torrentmanager.remove(tid, remove_data=remove_data)

            log.debug("remove_torrent(): successfully removed torrent: [%s]", tid)
        except Exception as e:
            log.warning("remove_torrent(): Problems removing torrent [%s]: %s", tid, e)

        try:
            del self.torrent_states.config[tid]
        except KeyError:
            log.warning("remove_torrent(): no saved state for torrent {}".format(tid))
            return True
        except Exception as e:
            log.warning("remove_torrent(): Error deleting state for torrent {}: {}".format(tid, e))
            return False
        else:
            return True

    def get_labels(self, id):
        lbl = ''

        try:
            if self.config['labelplus']:
                lbl = component.get("CorePlugin.LabelPlus").get_torrent_label_name(id)
            else:
                lbl = component.get("CorePlugin.Label")._status_get_label(id)
        except Exception as e:
            log.warning("get_labels(): problem obtaining torrent {} labels: {}".format(id, e))
            lbl = ''

        if type(lbl) is str and lbl:
            return [lbl]
        else:
            return []  # TODO: mherz' tote94 fix sets default to ["none"] as opposed to empty arr - why, do we want that?  to be able to create rules for 'none' label?

    def get_torrent_rules(self, id, torrent, tracker_rules, label_rules):

        total_rules = []

        if tracker_rules:
            try:
                for t in torrent.trackers:
                    for name, rules in tracker_rules.items():
                        log.debug("get_torrent_rules(): processing name = {}, rules = {}, url = {}, find = {} ".format(name, rules, t['url'], t['url'].find(name.lower())))
                        if (t['url'].find(name.lower()) != -1):
                            for rule in rules:
                                total_rules.append(rule)
            except Exception as e:
                log.warning("get_torrent_rules(): Exception with getting tracker rules for [{}]: {}".format(id, e))
                return total_rules

        if label_rules:
            # if torrent has labels check them
            labels = self.get_labels(id)

            for label in labels:
                if label in label_rules:
                    for rule in label_rules[label]:
                        total_rules.append(rule)

        log.debug("get_torrent_rules(): returning rules for [{}]: {}".format(id, total_rules))
        return total_rules

    # we don't use args or kwargs it just allows callbacks to happen cleanly
    @ensure_deferred
    async def periodic_scan(self, *args, **kwargs):
        log.debug("starting periodic_scan() exec...")

        if not self.config['enabled']:
            log.debug("plugin not enabled, skipping periodic_scan()")
            return

        max_seeds = int(self.config['max_seeds'])
        count_exempt = self.config['count_exempt']
        remove_data = self.config['remove_data']
        labelplus = self.config['labelplus']
        exemp_trackers = self.config['trackers']
        exemp_labels = self.config['labels']
        min_val = float(self.config['min'])
        min_val2 = float(self.config['min2'])
        remove = self.config['remove']
        tracker_rules = self.config['tracker_rules']
        rule_1_chk = self.config['rule_1_enabled']
        rule_2_chk = self.config['rule_2_enabled']
        labels_enabled = False  # default to false

        enabled_plugins = component.get("CorePluginManager").get_enabled_plugins()
        if ((labelplus and 'LabelPlus' in enabled_plugins) or
                (not labelplus and 'Label' in enabled_plugins)):
            labels_enabled = True
            # label_rules = self.config['label_rules']
            label_rules = {k.lower(): v for k, v in self.config['label_rules'].items()}  # TODO from mherz' tote94 fix; why is lower-keyed dict needed?
        else:
            log.warning("WARNING! Label and/or LabelPlus plugin(s) not active")
            log.warning("No labels will be checked for exemptions!")
            label_rules = {}

        # Negative max means unlimited seeds are allowed, so don't do anything
        if max_seeds < 0:
            return

        torrent_ids = self.torrentmanager.get_torrent_list()

        log.debug("Number of torrents: {0}".format(len(torrent_ids)))

        # If there are fewer torrents present than allowed, there's nothing to be done:
        if len(torrent_ids) <= max_seeds:
            return

        torrents = []
        ignored_torrents = []

        # relevant torrents to us exist and are finished
        for i in torrent_ids:
            t = self.torrentmanager.torrents.get(i, None)

            # TODO: deluge2.0 version of this script doesn't have this try-ex-else block:
            # likely because the end of this function is way more convoluted/feature-packed than in this - delugev1 - ver?
            try:
                finished = t.is_finished
                # finished = t.get_status(['is_finished'], update=True)['is_finished']  # TODO use this or attribute?
            except Exception as e:
                log.warning("periodic_scan(): Cannot obtain torrent 'is_finished' attribute: {}".format(e))
                continue
            else:
                if not finished:
                    continue

            ignored = self.torrent_states.config.get(i, False)
            trackers = t.trackers

            # check if trackers in exempted tracker list
            if exemp_trackers and not ignored:
                for tracker, ex_tracker in (
                    (t, ex_t) for t in trackers for ex_t in exemp_trackers
                ):
                    if (tracker['url'].find(ex_tracker.lower()) != -1):
                        log.debug("periodic_scan(): Found exempted tracker: [%s]" % (ex_tracker))
                        ignored = True
                        break

            # check if labels in exempted label list if Label(Plus) plugin is enabled
            if exemp_labels and labels_enabled and not ignored:
                # if torrent has labels check them
                labels = self.get_labels(i)

                for label, ex_label in (
                    (l, ex_l) for l in labels for ex_l in exemp_labels
                ):
                    if (label.find(ex_label.lower()) != -1):
                        log.debug("periodic_scan(): Found exempted label: [%s]" % (ex_label))
                        ignored = True
                        break

            # if torrent tracker or label in exemption list, or torrent ignored
            # insert in the ignored torrents list
            (ignored_torrents if ignored else torrents).append((i, t))  # (id, torrent) tuple

        log.debug("periodic_scan(): Number of finished torrents: {0}".format(len(torrents)))
        log.debug("periodic_scan(): Number of ignored/exempt torrents: {0}".format(len(ignored_torrents)))

        # now that we have trimmed active torrents
        # check again to make sure we still need to proceed
        if len(torrents) + (len(ignored_torrents) if count_exempt else 0) <= max_seeds:
            return

        # if we are counting ignored torrents towards our maximum
        # then these have to come off the top of our allowance
        if count_exempt:
            max_seeds -= len(ignored_torrents)
            if max_seeds < 0:
                max_seeds = 0

        # Alternate sort by primary and secondary criteria
        f1 = filter_funcs.get(self.config['filter'], _get_ratio)
        f2 = filter_funcs.get(self.config['filter2'], _get_ratio)
        if f1 == f2:
            sort_f = lambda x: f1(x)
        else:
            sort_f = lambda x: (f1(x), f2(x))

        torrents.sort(
            key=sort_f,
            reverse=False
        )

        changed = False

        # remove or pause these torrents
        for i, t in reversed(torrents[max_seeds:]):

            # check if free disk space below minimum
            if self.check_min_space():
                break  # we have enough space, do not remove any more

            log.debug(
                "periodic_scan(): starting remove-torrent rule checking for [%s], %s"
                % (i, t.get_status(['name'])['name'])
            )

            specific_rules = self.get_torrent_rules(i, t, tracker_rules, label_rules)

            remove_cond = False  # if torrent should be removed or paused

            # If there are specific rules, ignore general remove rules
            if specific_rules:
                # Sort rules according to logical operators; AND is evaluated first
                #
                # TODO: why do we want AND to be first? doesn't it make at least
                # very first AND pointless, as first rule's condition is dropped/ignored
                # anyways; think AND should be evaluated LAST instead!
                # oooor: don't sort at all, and leave the order as they're defined in conf/UI.
                # note it'd be perfect to disable the logic gate on first item as it's
                # ignored anyway;
                #
                # TODO2: also issues how specific_rules gets compiled: we process all tracker
                #        rules, followed by label rules. as it stands it's difficult to keep the
                #        _true_ rule order!
                specific_rules.sort(key=lambda rule: rule[0])

                first_spec_rule = specific_rules[0]
                remove_cond = filter_funcs.get(first_spec_rule[1])((i, t)) >= float(first_spec_rule[2])
                log.debug("1. spec rule %s: gate [%s]. fun: [%s], val: %s; remove_cond: %s",
                          i, first_spec_rule[0], first_spec_rule[1], float(first_spec_rule[2]), remove_cond)

                for rule_seq, rule in enumerate(specific_rules[1:], start=2):
                    check_filter = filter_funcs.get(rule[1])((i, t)) >= float(rule[2])
                    logic_gate = sel_funcs.get(rule[0])  # and/or/xor func
                    # TODO: should we be calling logic_gate() with single, tuple arg?
                    remove_cond = logic_gate((
                        check_filter,
                        remove_cond
                    ))
                    log.debug("%s. spec rule: gate [%s]. fun: [%s], val: %s; rule result: %s, aggregate remove_cond: %s",
                              rule_seq, rule[0], rule[1], float(rule[2]), check_filter, remove_cond)
            else:  # process general/global rules
                filter1_res = filter_funcs.get(self.config['filter'], _get_ratio)((i, t))
                filter2_res = filter_funcs.get(self.config['filter2'], _get_ratio)((i, t))

                # Get result of first condition test
                filter_1 = filter1_res >= min_val
                # Get result of second condition test
                filter_2 = filter2_res >= min_val2

                log.debug("[{}] filter1 enabled: [{}], filter2 enabled: [{}]".format(i, rule_1_chk, rule_2_chk))
                log.debug("filter1: {} >= {} = {}; filter2: {} >= {} = {}".format(filter1_res, min_val, filter_1, filter2_res, min_val2, filter_2))

                if rule_1_chk and rule_2_chk:
                    logic_gate = self.config['sel_func']
                    log.debug("both filters enabled, using logic gate: [{}]".format(logic_gate))

                    # If both rules active use custom logical function
                    logic_gate = sel_funcs.get(logic_gate)  # and/or/xor func

                    remove_cond = logic_gate((
                        filter_1,
                        filter_2
                    ))
                elif rule_1_chk and not rule_2_chk:
                    # Evaluate only first rule, since the other is not active
                    remove_cond = filter_1
                elif not rule_1_chk and rule_2_chk:
                    # Evaluate only second rule, since the other is not active
                    remove_cond = filter_2

            # If logical functions are satisfied, remove or pause torrent:
            if remove_cond:
                if not remove:
                    self.pause_torrent(t)
                else:
                    # note we deferToThread because of time.sleep() downstream
                    if await threads.deferToThread(lambda: self.remove_torrent(i, t, remove_data)):
                        changed = True
                    # sleep a bit post-removal to give time for hdd space to be freed up;
                    # on some seedboxes I've seen it takes a long time for space to be
                    # reported as freed up, which can cause too many torrents to be removed
                    # in the same invocation:
                    if self.config['hdd_space'] > 0.0 and self.config['post_removal_sleep_sec'] > 0.0:
                        await threads.deferToThread(lambda: time.sleep(self.config['post_removal_sleep_sec'])):

        # If a torrent exemption state has been removed save changes
        if changed:
            self.torrent_states.save()
