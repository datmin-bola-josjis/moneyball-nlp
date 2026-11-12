"""Stage B tests: alias matching, date window, sentence split, dedupe, relevance scoring.

Run with `make test` (unittest, so no extra dependency is required).
"""

from __future__ import annotations

import csv
import json
import random
import sys
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.scrape import apify_reddit, arctic_shift, relevance, subreddits  # noqa: E402
from src.scrape.aliases import AliasIndex, normalize  # noqa: E402
from src.scrape.players import Player, club_needles, pilot_subset  # noqa: E402
from src.scrape.reddit import (  # noqa: E402
    epoch_window,
    extract_for_player,
    search_query,
    season_bounds,
    subreddits_for,
    unique_raw_dir,
)
from src.scrape.reddit_client import keep_comment  # noqa: E402
from src.scrape.textops import (  # noqa: E402
    clean_text,
    is_bot_like,
    is_english,
    split_sentences,
    text_hash,
    word_count,
)

BRUNO_G = Player(
    player_id="p_bruno_g",
    name="Bruno Guimarães",
    aliases=("Bruno Guimarães", "Bruno Guimaraes", "Bruno G.", "Bruno G"),
    club="Newcastle United",
)
JOELINTON = Player(
    player_id="p_joelinton",
    name="Joelinton",
    aliases=("Joelinton",),
    club="Newcastle United",
)
BERNARDO = Player(
    player_id="p_bernardo",
    name="Bernardo Silva",
    aliases=("Bernardo Silva", "Bernardo"),
    club="Manchester City",
)
SILVA = Player(
    player_id="p_silva",
    name="Silva Santos",
    aliases=("Silva",),
    club="Fulham",
)
POPULATION = [BRUNO_G, JOELINTON, BERNARDO, SILVA]
CLUBS = [
    "Newcastle United",
    "Manchester City",
    "Fulham",
    "Manchester United",
    "Nottingham Forest",
]


class TextCleanTests(unittest.TestCase):
    def test_clean_strips_markdown_quote_and_links(self):
        raw = "> **Bruno G.** is [elite](http://x) &amp; press resistant"
        self.assertEqual(clean_text(raw), "Bruno G. is elite & press resistant")

    def test_hash_is_case_and_space_stable_across_sources(self):
        self.assertEqual(text_hash(clean_text("Same   Comment")), text_hash(clean_text("same comment")))

    def test_word_count_ignores_emoji_and_numbers(self):
        self.assertEqual(word_count("What a pass 10/10 🔥"), 3)

    def test_non_english_rejected_by_script_and_stopwords(self):
        self.assertFalse(is_english("Он лучший игрок лиги"))
        self.assertFalse(is_english("Fulham menang besar kemarin malam"))
        self.assertTrue(is_english("He was the best player on the pitch tonight"))

    def test_sentence_split_drops_fragments(self):
        sentences = split_sentences("Yes. Bruno G. ran the midfield. He never stops.")
        self.assertEqual(sentences, ["Bruno G. ran the midfield.", "He never stops."])

    def test_bot_markers(self):
        self.assertTrue(is_bot_like("AutoModerator", "Reminder: be civil."))
        self.assertTrue(is_bot_like("someone", "I am a bot, and this action was performed automatically"))
        self.assertFalse(is_bot_like("normal_user", "Bruno G. was brilliant again"))


class AliasTests(unittest.TestCase):
    def setUp(self):
        self.index = AliasIndex.build(POPULATION)

    def test_bare_surname_is_ambiguous(self):
        self.assertTrue(self.index.is_ambiguous("Silva"))
        self.assertTrue(self.index.is_ambiguous("Bernardo"))

    def test_full_name_is_unambiguous(self):
        self.assertFalse(self.index.is_ambiguous("Bruno Guimarães"))
        self.assertFalse(self.index.is_ambiguous("Joelinton"))

    def test_accent_and_apostrophe_normalisation(self):
        self.assertEqual(normalize("João Pedro"), "joao pedro")
        self.assertEqual(normalize("N'Golo Kanté"), "n'golo kante")
        self.assertEqual(normalize("O'Brien"), "o'brien")

    def test_possessive_does_not_block_a_mention(self):
        # "Saka's finishing" must still match the alias "Saka".
        self.assertEqual(normalize("Saka's finishing"), "saka finishing")
        self.assertEqual(normalize("Jones’ pass"), "jones pass")

    def test_possessive_mention_is_linked(self):
        saka = Player("p_saka", "Bukayo Saka", ("Bukayo Saka", "Saka"), "Arsenal")
        index = AliasIndex.build([saka])
        self.assertEqual(index.find_mentions("Saka's finishing was ruthless tonight", "p_saka"), "Saka")

    def test_find_mentions_matches_accent_free_spelling(self):
        # Text is written without the accent, the canonical alias wins.
        self.assertEqual(
            self.index.find_mentions("bruno guimaraes was everywhere", "p_bruno_g"),
            "Bruno Guimarães",
        )

    def test_find_mentions_rejects_other_player(self):
        self.assertIsNone(self.index.find_mentions("Saka was quiet today", "p_bruno_g"))

    def test_ambiguous_alias_needs_own_club_context(self):
        self.assertFalse(self.index.has_context("Silva was poor on the ball", "p_silva", CLUBS))
        self.assertTrue(
            self.index.has_context("Silva was poor, Fulham never recovered", "p_silva", CLUBS)
        )

    def test_other_club_is_not_context(self):
        # "City" belongs to another club, so it must not resolve Silva.
        self.assertFalse(
            self.index.has_context("Silva was poor against City", "p_silva", CLUBS)
        )

    def test_club_needles_use_only_safe_unique_words(self):
        # "Manchester" is shared by two clubs, so it identifies neither.
        self.assertEqual(
            set(club_needles("Manchester United", CLUBS)),
            {"manchester united", "manchesterunited"},
        )
        # "City" and "Forest" are ordinary English, so they cannot anchor alone.
        self.assertEqual(set(club_needles("Manchester City", CLUBS)), {"manchester city", "manchestercity"})
        self.assertEqual(
            set(club_needles("Nottingham Forest", CLUBS)),
            {"nottingham", "nottingham forest", "nottinghamforest"},
        )
        self.assertIn("newcastle", club_needles("Newcastle United", CLUBS))

    def test_club_subreddit_counts_as_context(self):
        self.assertTrue(
            self.index.has_context("Silva was poor on the ball", "p_silva", CLUBS, implicit_club=True)
        )

    def test_query_terms_rank_specific_aliases_first(self):
        terms = self.index.query_terms(BRUNO_G)
        self.assertEqual(terms[0], "Bruno Guimarães")
        # "Bruno G" and "Bruno G." normalise identically; one query term is kept.
        self.assertIn("Bruno G.", terms)
        self.assertEqual(len(terms), 2)

    def test_alias_debug_lists_shared_names(self):
        rows = dict((alias, owners) for alias, owners in AliasIndex.build(POPULATION).alias_debug())
        self.assertIn("silva", rows)


class QueryBuildTests(unittest.TestCase):
    def test_season_window_matches_config(self):
        start, end = season_bounds()
        self.assertEqual(start, datetime(2025, 7, 1, tzinfo=timezone.utc))
        # The last day must be covered in full, not just its midnight.
        self.assertEqual(end, datetime(2026, 5, 31, 23, 59, 59, tzinfo=timezone.utc))
        self.assertGreater(epoch_window()[1] - epoch_window()[0], 300 * 86400)

    def test_query_is_exact_phrase_without_retired_date_operator(self):
        # Reddit dropped Cloudsearch `timestamp:` ranges; including one would
        # search for the literal word and return nothing.
        query = search_query("Bruno Guimarães")
        self.assertEqual(query, '"Bruno Guimarães"')
        self.assertNotIn("timestamp", query.lower())

    def test_subreddits_include_league_and_own_club_only(self):
        subs = subreddits_for(BRUNO_G)
        self.assertIn("soccer", subs)
        self.assertIn("NUFC", subs)
        self.assertNotIn("MCFC", subs)

    def test_configured_subreddits_are_unique(self):
        names = subreddits.configured_subreddits()
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("PremierLeague", names)

    def test_keep_comment_filters_deleted_and_stickied(self):
        self.assertFalse(keep_comment({"body": "[removed]", "author": "x"}))
        self.assertFalse(keep_comment({"body": "good point", "author": "x", "stickied": True}))
        self.assertTrue(keep_comment({"body": "good point", "author": "fan"}))


class PopulationTests(unittest.TestCase):
    def test_duplicate_player_id_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "players.csv"
            path.write_text(
                "player_id,name_canonical,name_aliases,club\n"
                "p1,Alpha,,\n"
                "p1,Beta,,\n",
                encoding="utf-8",
            )
            from src.scrape.players import load_players

            with self.assertRaises(SystemExit):
                load_players(path)

    def test_alias_pipe_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "players.csv"
            path.write_text(
                "player_id,name_canonical,name_aliases,club\n"
                "p1,Bruno Guimarães,Bruno G.|Bruno Guimaraes,Newcastle United\n",
                encoding="utf-8",
            )
            from src.scrape.players import load_players

            (player,) = load_players(path)
            self.assertEqual(player.aliases[0], "Bruno Guimarães")
            self.assertIn("Bruno G.", player.aliases)

    def test_pilot_subset_is_deterministic_and_spread(self):
        players = [Player(f"p{i:02d}", f"Player {i}", (f"Player {i}",), None) for i in range(20)]
        values = {p.player_id: float(i) for i, p in enumerate(players)}
        first = pilot_subset(players, 5, values)
        second = pilot_subset(players, 5, values)
        self.assertEqual([p.player_id for p in first], [p.player_id for p in second])
        self.assertEqual(len(first), 5)
        self.assertLess(values[first[0].player_id], values[first[-1].player_id])


class RetentionTests(unittest.TestCase):
    """A fake client drives the real extraction path: no network, no creds."""

    def _tree(self, *bodies):
        children = []
        for i, body in enumerate(bodies):
            children.append(
                {
                    "kind": "t1",
                    "data": {
                        "id": f"c{i}",
                        "body": body,
                        "author": f"fan{i}",
                        "subreddit": "NUFC",
                        "created_utc": 1756000100.0,
                        "permalink": f"/r/NUFC/x/c{i}",
                        "score": 3,
                    },
                }
            )
        return [{}, {"data": {"children": children}}]

    def _client(self, comments, created=1756000000.0):
        tree = self._tree(*comments)
        outer = self

        class Stub:
            requests_made = 0

            def get(self, path, params=None):
                if path.endswith("/search"):
                    return {
                        "data": {
                            "children": [
                                {"data": {"id": "t1", "subreddit": "NUFC", "created_utc": created}},
                                {"data": {"id": "t0", "subreddit": "NUFC", "created_utc": 1500000000.0}},
                            ],
                            "after": None,
                        }
                    }
                outer.assertEqual(path, "/comments/t1")
                return tree

        return Stub()

    def _extract(self, client, player=BRUNO_G, quota=60):
        index = AliasIndex.build([player, JOELINTON])
        return extract_for_player(client, player, index, CLUBS, quota)

    def test_comment_and_sentences_are_both_kept(self):
        client = self._client(
            ["Bruno G. ran the midfield all game and never stopped pressing. "
             "Bruno G. also completed every pass he attempted under pressure."]
        )
        records = self._extract(client)
        self.assertEqual([r.unit_type for r in records], ["comment", "sentence", "sentence"])
        self.assertEqual(
            {r.text_id for r in records},
            {"rd_c0_p_bruno_g", "rd_c0_p_bruno_g_s0", "rd_c0_p_bruno_g_s1"},
        )
        self.assertEqual(records[1].parent_text_id, "rd_c0_p_bruno_g")

    def test_pronoun_only_sentence_is_not_linked(self):
        # Rule 3: a sentence is linked only if it names the player itself.
        client = self._client(
            ["Bruno G. ran the midfield all game and never stopped pressing. His passing was unreal."]
        )
        records = self._extract(client)
        self.assertEqual([r.unit_type for r in records], ["comment", "sentence"])

    def test_threads_outside_the_season_are_dropped(self):
        client = self._client(
            ["Bruno G. ran the midfield all game and never stopped pressing."], created=1500000000.0
        )
        self.assertEqual(self._extract(client), [])

    def test_comments_not_naming_the_player_are_dropped(self):
        client = self._client(["Joelinton was unplayable in that second half, honestly superb."])
        self.assertEqual(self._extract(client), [])

    def test_ambiguous_alias_without_club_context_is_dropped(self):
        client = self._client(
            ["Bernardo was quiet again and offered nothing going forward.", "Silva also struggled badly."]
        )
        index = AliasIndex.build([BRUNO_G, BERNARDO, SILVA])
        self.assertEqual(extract_for_player(client, BERNARDO, index, CLUBS, 60), [])

    def test_ambiguous_alias_with_club_context_is_kept(self):
        client = self._client(
            ["Bernardo was excellent, Manchester City controlled midfield from the first minute."]
        )
        index = AliasIndex.build([BRUNO_G, BERNARDO, SILVA])
        records = extract_for_player(client, BERNARDO, index, CLUBS, 60)
        self.assertTrue(records)
        self.assertTrue(all(r.matched_alias == "Bernardo" for r in records))

    def test_comment_naming_two_players_gets_distinct_text_ids(self):
        # One comment, two sample players: both records are legitimate and the
        # downstream join key must not collide.
        body = "Bruno G. and Joelinton ran that midfield together all evening."
        client = self._client([body])
        index = AliasIndex.build([BRUNO_G, JOELINTON])
        bruno = extract_for_player(client, BRUNO_G, index, CLUBS, 60)
        joel = extract_for_player(client, JOELINTON, index, CLUBS, 60)
        self.assertTrue(bruno and joel)
        ids = {r.text_id for r in [*bruno, *joel]}
        self.assertEqual(len(ids), len(bruno) + len(joel))
        self.assertEqual({r.player_id for r in bruno}, {"p_bruno_g"})
        self.assertEqual({r.player_id for r in joel}, {"p_joelinton"})

    def test_post_season_comment_in_an_old_thread_is_dropped(self):
        # Thread is in-season; the comment is from after the season ended.
        index = AliasIndex.build([BRUNO_G])
        client = self._client(["placeholder text for the stub thread"])
        later = {"kind": "t1", "data": {
            "id": "c0",
            "body": "Bruno G. ran the midfield all game and never stopped pressing.",
            "author": "fan", "subreddit": "NUFC",
            "created_utc": 1782000000.0,  # 2026-06-20, after the season window
            "permalink": "/r/NUFC/x/c0", "score": 3,
        }}
        late_tree = [{}, {"data": {"children": [later]}}]
        client.get = lambda path, params=None: (
            {"data": {"children": [{"data": {"id": "t1", "subreddit": "NUFC", "created_utc": 1756000000.0}}], "after": None}}
            if path.endswith("/search") else late_tree
        )
        self.assertEqual(extract_for_player(client, BRUNO_G, index, CLUBS, 60), [])

    def test_duplicate_comment_text_is_kept_once(self):
        body = "Bruno G. is the best midfielder in the league right now, no debate at all."
        client = self._client([body, body])
        comments = [r for r in self._extract(client) if r.unit_type == "comment"]
        self.assertEqual(len(comments), 1)

    def test_quota_stops_the_scrape(self):
        bodies = [f"Bruno G. dictated the tempo again in game number {i}, unreal." for i in range(6)]
        client = self._client(bodies)
        comments = [r for r in self._extract(client, quota=2) if r.unit_type == "comment"]
        self.assertEqual(len(comments), 2)

    def test_no_author_field_is_persisted(self):
        client = self._client(["Bruno G. was brilliant in midfield tonight, again."])
        record = self._extract(client)[0]
        self.assertNotIn("author", asdict(record))
        self.assertIn("text_clean_hash", asdict(record))


class ApifyProviderTests(unittest.TestCase):
    """The mapping layer is pure: actor-shaped dicts in, TextRecord out."""

    WINDOW = (1751328000.0, 1780271999.0)  # 2025-07-01 .. 2026-05-31 23:59:59Z

    def _post(self, **kw):
        base = {
            "type": "post",
            "id": "p1",
            "title": "Bruno G. masterclass",
            "selfText": "Bruno Guimaraes ran the midfield all evening, superb.",
            "author": "someone",
            "subreddit": "NUFC",
            "createdAt": "2025-11-20T10:00:00.000Z",
            "permalink": "/r/NUFC/comments/p1/x/",
            "score": 0,
        }
        base.update(kw)
        return base

    def _comment(self, **kw):
        base = {
            "type": "comment",
            "id": "c1",
            "body": "Bruno Guimaraes was everywhere tonight and never stopped pressing.",
            "author": "fan",
            # NOTE: the actor's `default` comment schema has no `subreddit`;
            # it must be inherited from the parent post or the permalink.
            "createdAt": "2025-11-20T11:00:00.000Z",
            "permalink": "/r/NUFC/comments/p1/x/c1/",
            "postId": "p1",
            "score": 4,
        }
        base.update(kw)
        return base

    def setUp(self):
        self.index = AliasIndex.build([BRUNO_G, JOELINTON])

    def _map(self, items, player=BRUNO_G, min_words=8, **kw):
        return apify_reddit.records_from_items(
            items, player, self.index, min_words, self.WINDOW, **kw
        )

    def test_comment_and_sentences_are_produced(self):
        records = self._map([self._comment()])
        kinds = [r.unit_type for r in records]
        self.assertEqual(kinds[0], "comment")
        self.assertIn("sentence", kinds)
        self.assertEqual(records[0].source, "reddit_apify")
        self.assertEqual(records[0].player_id, BRUNO_G.player_id)

    def test_unit_type_never_leaves_the_locked_schema(self):
        # PRD §8: comment | sentence | transcript_segment. Posts are carriers.
        records = self._map([self._post()])
        self.assertTrue(all(r.unit_type in {"comment", "sentence"} for r in records))
        self.assertEqual(records, [])

    def test_comment_inherits_subreddit_from_parent_post(self):
        records = self._map([self._post(), self._comment()])
        self.assertTrue(records)
        self.assertEqual({r.subreddit for r in records}, {"NUFC"})

    def test_subreddit_falls_back_to_permalink(self):
        # No post in the payload, so only the permalink can supply it.
        records = self._map([self._comment()])
        self.assertEqual({r.subreddit for r in records}, {"NUFC"})

    def test_deleted_and_removed_units_are_dropped(self):
        self.assertEqual(self._map([self._comment(body="[deleted]")]), [])
        self.assertEqual(self._map([self._comment(body="[removed]")]), [])

    def test_bot_comments_are_dropped(self):
        bot = self._comment(
            body="I am a bot, and this action was performed automatically. Bruno Guimaraes.",
        )
        self.assertEqual(self._map([bot]), [])
        automod = self._comment(author="AutoModerator")
        self.assertEqual(self._map([automod]), [])

    def test_non_english_is_dropped(self):
        self.assertEqual(
            self._map([self._comment(body="Bruno Guimaraes bermain sangat bagus malam ini kawan.")]),
            [],
        )

    def test_ambiguous_alias_without_club_context_is_dropped(self):
        index = AliasIndex.build([BRUNO_G, BERNARDO, SILVA])
        bare = self._comment(body="Bernardo was quiet again and offered nothing going forward.")
        records = apify_reddit.records_from_items(
            [bare], BERNARDO, index, 8, self.WINDOW, league_clubs=CLUBS
        )
        self.assertEqual(records, [])

    def test_ambiguous_alias_resolves_with_club_context(self):
        index = AliasIndex.build([BRUNO_G, BERNARDO, SILVA])
        named = self._comment(
            body="Bernardo was excellent, Manchester City controlled midfield from the first minute."
        )
        records = apify_reddit.records_from_items(
            [named], BERNARDO, index, 8, self.WINDOW, league_clubs=CLUBS
        )
        self.assertTrue(records)

    def test_own_club_subreddit_supplies_context(self):
        # Comment sits in MCFC, Bernardo's own club sub: the bare surname is safe.
        index = AliasIndex.build([BRUNO_G, BERNARDO, SILVA])
        bare = self._comment(
            body="Bernardo was quiet again and offered nothing going forward.",
            permalink="/r/MCFC/comments/p1/x/c1/",
        )
        records = apify_reddit.records_from_items(
            [bare],
            BERNARDO,
            index,
            8,
            self.WINDOW,
            league_clubs=CLUBS,
            club_subreddits=["MCFC"],
        )
        self.assertTrue(records)

    def test_other_club_subreddit_gives_no_context(self):
        # Same bare surname, but posted in Newcastle's sub. That is not evidence
        # that the comment is about Manchester City's Bernardo.
        index = AliasIndex.build([BRUNO_G, BERNARDO, SILVA])
        bare = self._comment(body="Bernardo was quiet again and offered nothing going forward.")
        records = apify_reddit.records_from_items(
            [bare],
            BERNARDO,
            index,
            8,
            self.WINDOW,
            league_clubs=CLUBS,
            club_subreddits=["MCFC"],
        )
        self.assertEqual(records, [])

    def test_quota_caps_units_per_player(self):
        bodies = [
            f"Bruno Guimaraes dictated the tempo again in game number {i}, unreal."
            for i in range(6)
        ]
        items = [self._comment(id=f"c{i}", body=b) for i, b in enumerate(bodies)]
        comments = [r for r in self._map(items, quota=2) if r.unit_type == "comment"]
        self.assertEqual(len(comments), 2)

    def test_text_id_carries_player_id_so_two_players_never_collide(self):
        both = [self._comment(body="Bruno Guimaraes and Joelinton dominated the midfield tonight.")]
        bruno = self._map(both, player=BRUNO_G)
        joel = self._map(both, player=JOELINTON)
        self.assertTrue(bruno and joel)
        self.assertFalse({r.text_id for r in bruno} & {r.text_id for r in joel})

    def test_text_about_another_player_is_dropped(self):
        self.assertEqual(self._map([self._comment(body="Joelinton was unplayable in that half, honestly.")]), [])

    def test_out_of_season_text_is_dropped(self):
        self.assertEqual(self._map([self._comment(createdAt="2026-08-01T00:00:00.000Z")]), [])

    def test_short_text_is_dropped(self):
        self.assertEqual(self._map([self._comment(body="Bruno good.")]), [])

    def test_duplicate_text_kept_once(self):
        dup = self._comment()
        comments = [r for r in self._map([dup, dict(dup)]) if r.unit_type == "comment"]
        self.assertEqual(len(comments), 1)

    def test_missing_score_does_not_crash(self):
        # The actor emits score 0 or omits it on the public-feed path.
        records = self._map([self._comment(score=None)])
        self.assertTrue(records)
        self.assertEqual(records[0].engagement, 0)

    def test_author_identity_never_reaches_disk(self):
        # AGENTS.md rule 11: no commenter username is stored.
        payload = [
            self._comment(author="some_real_username"),
            self._post(author="another_user"),
        ]
        cleaned = apify_reddit.scrub_identity(payload)
        self.assertTrue(all("author" not in item for item in cleaned))
        self.assertTrue(all("authorId" not in item for item in cleaned))
        # everything else survives
        self.assertEqual(cleaned[0]["body"], payload[0]["body"])

    def test_bot_filter_still_runs_before_scrubbing(self):
        # Scrubbing happens at persist time, so bot detection still has the name.
        bot = self._comment(author="AutoModerator")
        self.assertEqual(self._map([bot]), [])

    def test_empty_and_malformed_items_are_ignored(self):
        items = [{}, {"type": "weird"}, {"type": "post"}]
        self.assertEqual(self._map(items), [])

    def test_cost_estimate_charges_comments_per_post(self):
        # 5 posts x 12 comments = 60 comments per player, not 12.
        est = apify_reddit.estimate_cost(10, 5, 12)
        self.assertEqual(est["posts"], 50)
        self.assertEqual(est["comments"], 600)

    def test_actor_input_is_player_scoped(self):
        cfg = {"max_posts_per_player": 5, "max_comments_per_post": 12}
        payload = apify_reddit.build_input(BRUNO_G, self.index, cfg)
        self.assertEqual(payload["maxPostsPerSource"], 5)
        self.assertEqual(payload["maxCommentsPerPost"], 12)
        self.assertTrue(payload["includeComments"])
        self.assertEqual(payload["searchSubreddit"], "NUFC")
        # `searchQuery` singular: `searchQueries` is not in the actor schema and
        # is silently dropped, which made the first live pilot return hot posts.
        self.assertEqual(payload["searchQuery"], "Bruno Guimarães")
        self.assertNotIn("searchQueries", payload)

    def test_disabled_provider_refuses_to_run(self):
        # Forced off here: the real config is a team decision and may be either
        # way, so the test must not depend on its current value.
        cfg = apify_reddit.load_config()
        apify_cfg = cfg["text_sources"]["reddit"]["apify"]
        original = dict(apify_cfg)
        apify_cfg["enabled"] = False
        try:
            with self.assertRaises(SystemExit):
                apify_reddit.run([BRUNO_G], client=object())
        finally:
            apify_cfg.update(original)

    def test_absolute_permalink_is_not_prefixed_twice(self):
        # Live run produced `https://www.reddit.comhttps://www.reddit.com/...`
        records = self._map([self._comment(permalink="https://www.reddit.com/r/NUFC/comments/p1/x/c1/")])
        self.assertEqual(records[0].url, "https://www.reddit.com/r/NUFC/comments/p1/x/c1/")
        relative = self._map([self._comment(permalink="/r/NUFC/comments/p1/x/c1/")])
        self.assertEqual(relative[0].url, "https://www.reddit.com/r/NUFC/comments/p1/x/c1/")

    def test_interrupted_run_aborts_the_actor(self):
        # A kill must not leave the actor billing in the background.
        class Aborts(apify_reddit.ApifyClient):
            def __init__(self, *a, **kw):
                self.aborted = []
                self._props = {"searchQuery"}
                self._session = None

            def _await_run(self, run_id, dataset_id, timeout_s):
                raise KeyboardInterrupt

            def abort_run(self, run_id):
                self.aborted.append(run_id)

            def _get(self, path, params=None):
                return {"data": {"id": "run-1", "defaultDatasetId": "ds-1"}}

        class Resp:
            status_code = 201

            def json(self):
                return {"data": {"id": "run-1", "defaultDatasetId": "ds-1"}}

        client = Aborts()
        client._session = type("S", (), {"post": lambda *a, **kw: Resp()})()
        with self.assertRaises(KeyboardInterrupt):
            client.run_actor({"searchQuery": "x"})
        self.assertEqual(client.aborted, ["run-1"])

    def test_credit_guard_blocks_before_any_request(self):
        # A cap larger than the real balance used to be fictional: the run died
        # at the payment step mid-list instead of up front.
        cfg = apify_reddit.load_config()
        apify_cfg = cfg["text_sources"]["reddit"]["apify"]
        original = dict(apify_cfg)
        apify_cfg.update(
            {"enabled": True, "max_posts_per_player": 15, "max_comments_per_post": 12,
             "max_cost_usd": 100.0}
        )

        class Broke(apify_reddit.ApifyClient):
            def __init__(self, *a, **kw):
                pass

            def credit_remaining(self, free_credits_usd=5.0):
                return 0.01

        try:
            with self.assertRaises(SystemExit) as ctx:
                apify_reddit.run([BRUNO_G], client=Broke())
            self.assertIn("credit", str(ctx.exception).lower())
        finally:
            apify_cfg.update(original)

    def test_cost_estimate_matches_the_published_prices(self):
        # 1 player, 15 posts, 12 comments each.
        est = apify_reddit.estimate_cost(1, 15, 12)
        expected = (
            apify_reddit.PRICE_START
            + 15 * apify_reddit.PRICE_PER_POST
            + 180 * apify_reddit.PRICE_PER_COMMENT
        )
        self.assertAlmostEqual(est["usd"], round(expected, 2), places=2)
        self.assertEqual(est["comments"], 180)

    def test_token_is_sent_as_bearer_not_query_param(self):
        # A token in the query string leaks into request logs; the first live
        # run printed it into verbose output that way.
        client = apify_reddit.ApifyClient(token="secret-token")
        self.assertEqual(client._session.headers["Authorization"], "Bearer secret-token")

    def test_subreddit_parsed_from_absolute_permalink(self):
        absolute = {"permalink": "https://www.reddit.com/r/MCFC/comments/1/x/c1/"}
        self.assertEqual(apify_reddit._subreddit_of(absolute, {}), "MCFC")
        relative = {"permalink": "/r/NUFC/comments/p1/x/c1/"}
        self.assertEqual(apify_reddit._subreddit_of(relative, {}), "NUFC")

    def test_unknown_input_key_is_rejected(self):
        # Guards the class of bug that broke the first live pilot.
        client = apify_reddit.ApifyClient(token="x")
        client._props = {"searchQuery", "sort"}
        with self.assertRaises(apify_reddit.ApifyError):
            client.validate_input({"searchQueries": ["a"], "sort": "relevance"})
        client.validate_input({"searchQuery": "a", "sort": "relevance"})

    def test_cost_cap_blocks_the_run_before_any_request(self):
        cfg = apify_reddit.load_config()
        apify_cfg = cfg["text_sources"]["reddit"]["apify"]
        original = dict(apify_cfg)
        apify_cfg.update(
            {"enabled": True, "max_posts_per_player": 5, "max_comments_per_post": 100,
             "max_cost_usd": 0.01}
        )
        try:
            with self.assertRaises(SystemExit) as ctx:
                apify_reddit.run([BRUNO_G], client=object())
            self.assertIn("exceeds", str(ctx.exception))
        finally:
            apify_cfg.update(original)


class ArcticShiftProviderTests(unittest.TestCase):
    """Archive shape in, TextRecord out. No network: the session is stubbed."""

    WINDOW_START = 1751328000.0  # 2025-07-01, epoch: the archive ignores strings
    # 2025-11-20T11:00:00Z, inside the configured season window.
    CREATED = 1763636400.0

    def _comment(self, **kw):
        base = {
            "id": "c1",
            "body": "Bruno Guimaraes was everywhere tonight and never stopped pressing.",
            "author": "fan",
            "subreddit": "NUFC",
            "link_id": "t3_abc",
            "created_utc": self.CREATED,
            "permalink": "/r/NUFC/comments/abc/x/c1/",
            "score": 7,
            "stickied": False,
            "distinguished": None,
        }
        base.update(kw)
        return base

    def setUp(self):
        self.index = AliasIndex.build([BRUNO_G, JOELINTON])

    def _map(self, comments, player=BRUNO_G, min_words=8, **kw):
        return arctic_shift.records_from_comments(
            comments, player, self.index, CLUBS, min_words, **kw
        )

    # ------------------------------------------------------------- mapping
    def test_comment_and_sentences_are_produced(self):
        records = self._map([self._comment(
            body="Kieran Trippier was excellent at right back tonight. Bruno Guimaraes owned midfield."
        )])
        kinds = [r.unit_type for r in records]
        self.assertEqual(kinds[0], "comment")
        self.assertIn("sentence", kinds)
        self.assertEqual({r.source for r in records}, {"reddit_arctic"})
        self.assertEqual({r.thread_id for r in records}, {"abc"})

    def test_native_archive_shape_is_mapped_without_auth(self):
        records = self._map([self._comment()])
        self.assertEqual(records[0].player_id, BRUNO_G.player_id)
        self.assertEqual(records[0].subreddit, "NUFC")
        self.assertEqual(records[0].engagement, 7)
        self.assertTrue(records[0].url.startswith("https://www.reddit.com/r/NUFC/"))

    def test_deleted_stickied_and_bot_comments_are_dropped(self):
        for bad in (
            self._comment(body="[deleted]"),
            self._comment(stickied=True),
            self._comment(author="AutoModerator"),
        ):
            self.assertEqual(self._map([bad]), [], bad)

    def test_short_and_out_of_season_comments_are_dropped(self):
        self.assertEqual(self._map([self._comment(body="Bruno good.")]), [])
        self.assertEqual(self._map([self._comment(created_utc=1782000000.0)]), [])

    def test_quota_caps_comment_units(self):
        comments = [
            self._comment(id=f"c{i}", body=f"Bruno Guimaraes dictated tempo again in game {i}, unreal.")
            for i in range(5)
        ]
        kept = [r for r in self._map(comments, quota=2) if r.unit_type == "comment"]
        self.assertEqual(len(kept), 2)

    def test_duplicate_comment_kept_once(self):
        dup = self._comment()
        kept = [r for r in self._map([dup, dict(dup)]) if r.unit_type == "comment"]
        self.assertEqual(len(kept), 1)

    def test_query_term_is_the_last_name_token(self):
        # Two-word `body=` phrases answer 422 unconditionally.
        self.assertEqual(arctic_shift.query_terms(BRUNO_G), ["guimaraes"])
        jose = Player(player_id="p_sa", name="José Sá", aliases=("José Sá", "Sá"), club="Wolverhampton Wanderers")
        self.assertEqual(arctic_shift.query_terms(jose), ["sa"])

    def test_league_subreddits_are_not_queried(self):
        # r/soccer and r/PremierLeague are not body-searchable in the archive.
        subs = arctic_shift.player_subreddits(BRUNO_G)
        self.assertEqual(subs, ["NUFC"])
        self.assertNotIn("soccer", subs)

    # -------------------------------------------------------------- client
    def _client(self, statuses, payloads=None, cache_dir=None):
        class Resp:
            def __init__(self, code, body, headers=None):
                self.status_code = code
                self._body = body
                self.headers = headers or {}
                self.text = json.dumps(body)[:200]

            def json(self):
                return self._body

        class Session:
            def __init__(self):
                self.headers = {}
                self.calls = []

            def get(self, url, params=None, timeout=None):
                self.calls.append(dict(params or {}))
                code = statuses[min(len(self.calls) - 1, len(statuses) - 1)]
                body = (payloads or {}).get(params.get("limit"), {"data": []})
                return Resp(code, body)

        session = Session()
        tmp = cache_dir or Path(tempfile.mkdtemp())
        client = arctic_shift.ArcticShiftClient(session=session, cache_dir=tmp)
        client.retry_gap = 0.0
        client.min_interval = 0.0
        return client, session

    def test_422_then_200_returns_the_page(self):
        page = {"data": [{"id": "c1", "body": "x", "created_utc": 1}]}
        client, session = self._client([422, 200], {100: page})
        rows = client.search_comments("NUFC", "guimaraes", self.WINDOW_START)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(session.calls), 2)

    def test_limit_ladder_drops_on_422(self):
        # limit=100 always 422, limit=25 answers: the ladder must lower the limit.
        page = {"data": [{"id": "c9", "body": "y", "created_utc": 1}]}

        class Resp:
            def __init__(self, code, body, headers=None):
                self.status_code = code
                self._body = body
                self.headers = headers or {}
                self.text = ""

            def json(self):
                return self._body

        class Session:
            def __init__(self):
                self.headers = {}
                self.limits = []

            def get(self, url, params=None, timeout=None):
                self.limits.append(params["limit"])
                return Resp(200, page) if params["limit"] <= 25 else Resp(422, {})

        session = Session()
        client = arctic_shift.ArcticShiftClient(
            session=session, cache_dir=Path(tempfile.mkdtemp())
        )
        client.retry_gap = 0.0
        client.min_interval = 0.0
        rows = client.search_comments("WWFC", "tchatchoua", self.WINDOW_START)
        self.assertEqual(len(rows), 1)
        self.assertEqual(session.limits, [100, 100, 100, 100, 25])
        self.assertEqual(client.last_limit, 25)

    def test_persistent_422_raises(self):
        client, _ = self._client([422])
        with self.assertRaises(arctic_shift.ArcticShiftError):
            client.search_comments("WWFC", "jose", self.WINDOW_START)

    def test_backoff_grows_instead_of_staying_fixed(self):
        # AGENTS.md requires exponential backoff, not a constant gap.
        slept: list[float] = []
        original = arctic_shift.time.sleep
        arctic_shift.time.sleep = lambda s: slept.append(s)
        try:
            client, _ = self._client([422])
            client.retry_gap = 10.0
            client.limit_ladder = [100]  # one step, so backoff is not repeated per limit
            with self.assertRaises(arctic_shift.ArcticShiftError):
                client.search_comments("WWFC", "jose", self.WINDOW_START)
        finally:
            arctic_shift.time.sleep = original
        self.assertEqual(slept, [10.0, 20.0, 40.0])

    def test_403_stops_instead_of_retrying(self):
        client, session = self._client([403])
        with self.assertRaises(arctic_shift.ArcticShiftBlocked):
            client.search_comments("NUFC", "guimaraes", self.WINDOW_START)
        self.assertEqual(len(session.calls), 1)

    def _reset_client(self, headers: dict, status: int = 429):
        """Client whose stub answers `status` with the given headers, then 200."""

        class Resp:
            def __init__(self, code, hdrs):
                self.status_code = code
                self.headers = hdrs
                self.text = ""
                self._body = {"data": []}

            def json(self):
                return self._body

        class Session:
            def __init__(self):
                self.headers = {}
                self.calls = 0

            def get(self, url, params=None, timeout=None):
                self.calls += 1
                return Resp(status, headers) if self.calls == 1 else Resp(200, {})

        session = Session()
        client = arctic_shift.ArcticShiftClient(
            session=session, cache_dir=Path(tempfile.mkdtemp())
        )
        client.retry_gap = 0.0
        client.min_interval = 0.0
        return client, session

    def test_rate_limit_reset_header_is_waited_out(self):
        # The archive advertises when it will accept a request again; sending
        # early is what turns one 422 into eight.
        slept: list[float] = []
        original = arctic_shift.time.sleep
        arctic_shift.time.sleep = lambda s: slept.append(s)
        try:
            client, session = self._reset_client({"x-ratelimit-reset": "35"})
            client.search_comments("NUFC", "guimaraes", self.WINDOW_START)
        finally:
            arctic_shift.time.sleep = original
        self.assertEqual(session.calls, 2)
        self.assertIn(35.0, slept)

    def test_malformed_reset_at_falls_back_to_seconds(self):
        slept: list[float] = []
        original = arctic_shift.time.sleep
        arctic_shift.time.sleep = lambda s: slept.append(s)
        try:
            client, _ = self._reset_client(
                {"x-ratelimit-reset-at": "not-a-number", "x-ratelimit-reset": "12"}
            )
            client.search_comments("NUFC", "guimaraes", self.WINDOW_START)
        finally:
            arctic_shift.time.sleep = original
        self.assertIn(12.0, slept)

    def test_reset_beyond_the_ceiling_stops_instead_of_requesting_early(self):
        client, session = self._reset_client({"x-ratelimit-reset": "9999"})
        client.max_reset_wait = 120.0
        with self.assertRaises(arctic_shift.ArcticShiftBlocked):
            client.search_comments("NUFC", "guimaraes", self.WINDOW_START)
        self.assertEqual(session.calls, 1)

    def test_rate_limit_without_any_reset_header_stops(self):
        client, session = self._reset_client({})
        with self.assertRaises(arctic_shift.ArcticShiftBlocked):
            client.search_comments("NUFC", "guimaraes", self.WINDOW_START)
        self.assertEqual(session.calls, 1)

    def test_throttled_200_is_not_cached_as_an_empty_page(self):
        # {"data": null, "error": "Timeout. Maybe slow down a bit"} arrives as 200;
        # caching it would freeze an empty page into the run forever.
        class Resp:
            def __init__(self, code, body):
                self.status_code = code
                self._body = body
                self.headers = {}
                self.text = json.dumps(body)[:100]

            def json(self):
                return self._body

        class Session:
            def __init__(self):
                self.headers = {}
                self.calls = 0

            def get(self, url, params=None, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    return Resp(200, {"data": None, "error": "Timeout. Maybe slow down a bit"})
                return Resp(200, {"data": [{"id": "c1", "body": "x", "created_utc": 5}]})

        cache_dir = Path(tempfile.mkdtemp())
        client = arctic_shift.ArcticShiftClient(session=Session(), cache_dir=cache_dir)
        client.retry_gap = 0.0
        client.min_interval = 0.0
        rows = client.search_comments("NUFC", "guimaraes", self.WINDOW_START)
        self.assertEqual(len(rows), 1)
        # The cache must hold the real page, not the throttled answer.
        stored = json.loads(next(cache_dir.glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(len(stored), 1)

    def test_cheap_cached_rung_is_found_without_any_request(self):
        # A page cached at limit=25 must satisfy the call even though 100 is tried
        # first, otherwise every rerun re-requests the expensive rung for nothing.
        cache_dir = Path(tempfile.mkdtemp())
        seed, _ = self._client([200], {25: {"data": [{"id": "c1", "body": "x", "created_utc": 5}]}},
                               cache_dir=cache_dir)
        seed.limit_ladder = [25]
        seed.search_comments("WWFC", "tchatchoua", self.WINDOW_START)

        client, session = self._client([200], {}, cache_dir=cache_dir)
        rows = client.search_comments("WWFC", "tchatchoua", self.WINDOW_START)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(session.calls), 0)
        self.assertEqual(client.last_limit, 25)

    def test_blocked_refusal_aborts_the_whole_run(self):
        # A 403 on one player must not be swallowed into "no texts for this player".
        class Blocked:
            requests_made = 0
            last_limit = 100

            def search_comments(self, *a, **kw):
                raise arctic_shift.ArcticShiftBlocked("HTTP 403 - access refused")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(arctic_shift.ArcticShiftBlocked):
                arctic_shift.run([BRUNO_G], client=Blocked(), tag="blocked", root=Path(tmp))

    def test_non_retryable_status_raises_at_once(self):
        client, session = self._client([403])
        with self.assertRaises(arctic_shift.ArcticShiftError):
            client.search_comments("NUFC", "guimaraes", self.WINDOW_START)
        self.assertEqual(len(session.calls), 1)

    def test_successful_page_is_cached_and_not_refetched(self):
        page = {"data": [{"id": "c1", "body": "x", "created_utc": 1}]}
        client, session = self._client([200], {100: page})
        client.search_comments("NUFC", "guimaraes", self.WINDOW_START)
        rows = client.search_comments("NUFC", "guimaraes", self.WINDOW_START)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(session.calls), 1)  # second call never touched network

    def test_empty_result_is_a_real_answer_not_an_error(self):
        client, _ = self._client([200], {100: {"data": []}})
        self.assertEqual(client.search_comments("BurnleyFC", "trippier", self.WINDOW_START), [])

    def test_cache_on_disk_carries_no_username(self):
        # Found in the first live pilot: the raw archive answer includes `author`,
        # `author_fullname`, `approved_by`, `banned_by`, `awarders`, `link_author`
        # and `profile_img` (the commenter's avatar URL). Writing it unscrubbed
        # breaks AGENTS.md rule 11, so only the fields the pipeline reads survive.
        page = {"data": [self._comment(
            author="some_real_username",
            author_fullname="t2_abc",
            approved_by="modname",
            awarders=["giver"],
            link_author="post_author_name",
            profile_img="https://styles.redditmedia.com/avatar.jpg",
        )]}
        cache_dir = Path(tempfile.mkdtemp())
        client, _ = self._client([200], {100: page}, cache_dir=cache_dir)
        client.search_comments("NUFC", "guimaraes", self.WINDOW_START)
        stored = json.loads(next(cache_dir.glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(
            set(stored[0]),
            {"id", "body", "created_utc", "subreddit", "score", "permalink",
             "link_id", "stickied", "_skip"},
        )
        # The bot verdict survives the scrub, so a replayed row is still filtered.
        self.assertEqual(stored[0]["_skip"], False)

    def test_bot_verdict_is_taken_before_scrubbing(self):
        bot = self._comment(author="AutoModerator")
        cache_dir = Path(tempfile.mkdtemp())
        client, _ = self._client([200], {100: {"data": [bot]}}, cache_dir=cache_dir)
        cached = client.search_comments("NUFC", "guimaraes", self.WINDOW_START)
        self.assertEqual(cached[0]["_skip"], True)
        self.assertNotIn("author", cached[0])
        self.assertEqual(self._map(cached), [])

    def test_window_is_sent_as_epoch_seconds(self):
        # Epoch integers are the format verified to filter here; the same test
        # checks both bounds reach the first request.
        page = {"data": []}
        client, session = self._client([200], {100: page})
        client.search_comments("Everton", "pickford", self.WINDOW_START, 1780271999)
        self.assertEqual(session.calls[0]["after"], 1751328000)
        self.assertEqual(session.calls[0]["before"], 1780271999)
        self.assertIsInstance(session.calls[0]["after"], int)

    # ----------------------------------------------------------------- run
    def test_run_writes_raw_summary_and_interim_without_identity(self):
        page = [
            self._comment(id="c1"),
            self._comment(id="c2", body="Joelinton was unplayable in that half, honestly."),
        ]

        class Stub:
            requests_made = 4
            last_limit = 100

            def __init__(self):
                self.calls = []

            def search_comments(self, subreddit, term, after, before=None):
                self.calls.append((subreddit, term, before))
                # One page only: the second call returns nothing.
                return page if len(self.calls) == 1 else []

        with tempfile.TemporaryDirectory() as tmp:
            stub = Stub()
            interim = arctic_shift.run([BRUNO_G], client=stub, tag="unit", root=Path(tmp))
            rows = [json.loads(l) for l in interim.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(rows)
            self.assertEqual({r["source"] for r in rows}, {"reddit_arctic"})
            raw = list((Path(tmp) / "data" / "raw" / "reddit").glob("arctic-unit-*"))
            self.assertEqual(len(raw), 1)
            payload = json.loads((raw[0] / f"{BRUNO_G.player_id}.comments.json").read_text(encoding="utf-8"))
            self.assertTrue(all("author" not in item for item in payload))
            summary = json.loads((raw[0] / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["provider"], "arctic_shift")
            self.assertIn("failed_requests", summary)
            self.assertEqual(summary["comments"], sum(1 for r in rows if r["unit_type"] == "comment"))

    def test_run_never_exceeds_the_per_player_quota(self):
        # The first live pilot kept 89 and 93 comments against a quota of 60: the
        # mapper was called with quota=None, so one full page overshot.
        from src.scrape import reddit as reddit_mod
        cfg = reddit_mod.load_config()["text_sources"]["reddit"]
        quota = int(cfg["max_texts_per_player"])
        page = [
            self._comment(id=f"c{i}", body=f"Bruno Guimaraes dictated tempo again in game {i}, unreal.")
            for i in range(quota * 2)
        ]

        class Stub:
            requests_made = 0
            last_limit = 100

            def __init__(self):
                self.calls = 0

            def search_comments(self, subreddit, term, after, before=None):
                self.calls += 1
                # Every page is full, so only the quota can stop the walk.
                return page

        with tempfile.TemporaryDirectory() as tmp:
            stub = Stub()
            interim = arctic_shift.run([BRUNO_G], client=stub, tag="quota", root=Path(tmp))
            rows = [json.loads(l) for l in interim.read_text(encoding="utf-8").splitlines()]
            kept = sum(1 for r in rows if r["unit_type"] == "comment")
            self.assertEqual(kept, quota)
            self.assertEqual(stub.calls, 1)

    def test_pagination_walks_until_short_page(self):
        full = [self._comment(id=f"c{i}", body=f"Bruno Guimaraes ran midfield in game {i} tonight.")
                for i in range(100)]

        class Stub:
            requests_made = 0
            last_limit = 100

            def __init__(self):
                self.befores = []

            def search_comments(self, subreddit, term, after, before=None):
                self.befores.append(before)
                # First page is bounded above by the season end, not `None`.
                return full if before == epoch_window()[1] else full[:3]

        with tempfile.TemporaryDirectory() as tmp:
            stub = Stub()
            arctic_shift.run([BRUNO_G], client=stub, tag="page", root=Path(tmp))
            # Page 1 is capped by the season end; page 2 by the oldest row seen.
            self.assertEqual(stub.befores, [epoch_window()[1], float(int(self.CREATED))])

class RawOutputTests(unittest.TestCase):
    def test_second_run_in_the_same_second_gets_its_own_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = unique_raw_dir("pilot", base=Path(tmp))
            (first / "texts.jsonl").write_text("earlier run", encoding="utf-8")
            second = unique_raw_dir("pilot", base=Path(tmp))
            self.assertNotEqual(first, second)
            self.assertEqual((first / "texts.jsonl").read_text(encoding="utf-8"), "earlier run")
            self.assertTrue(second.is_dir())


class RelevanceTests(unittest.TestCase):
    def test_unlabelled_rows_are_ignored_and_rate_computed(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "review.csv"
            with sheet.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=relevance.FIELDS)
                writer.writeheader()
                for i, label in enumerate(["y", "yes", "n", ""]):
                    writer.writerow(
                        {
                            "text_id": f"t{i}",
                            "player_id": "p1",
                            "subreddit": "soccer",
                            "created_at": "2025-09-01",
                            "url": "",
                            "text_clean": "Bruno G. was excellent",
                            "relevant": label,
                        }
                    )
            out = Path(tmp) / "report.md"
            original = relevance.REPORT
            relevance.REPORT = out
            try:
                path, stats = relevance.score_review(sheet)
            finally:
                relevance.REPORT = original
            self.assertEqual(stats["labelled"], 3)
            self.assertEqual(stats["relevant"], 2)
            self.assertAlmostEqual(stats["rate"], 2 / 3)
            self.assertTrue(path.read_text(encoding="utf-8").startswith("# Relevansi"))

    def test_missing_sheet_is_an_error(self):
        with self.assertRaises(SystemExit):
            relevance.score_review(Path(tempfile.gettempdir()) / "does-not-exist.csv")

    def _sheet(self, tmp, labels):
        sheet = Path(tmp) / "review.csv"
        with sheet.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=relevance.FIELDS)
            writer.writeheader()
            for i, label in enumerate(labels):
                writer.writerow(
                    {
                        "text_id": f"t{i}",
                        "player_id": "p1",
                        "subreddit": "NUFC",
                        "created_at": "2025-09-01",
                        "url": "",
                        "text_clean": "Bruno G. was excellent",
                        "relevant": label,
                    }
                )
        return sheet

    def test_high_rate_on_a_handful_of_labels_does_not_pass_the_gate(self):
        # 3/3 relevant is 100%, but the gate asks for 100 labelled texts.
        with tempfile.TemporaryDirectory() as tmp:
            sheet = self._sheet(tmp, ["y", "y", "y"])
            out = Path(tmp) / "report.md"
            original = relevance.REPORT
            relevance.REPORT = out
            try:
                path, stats = relevance.score_review(sheet)
            finally:
                relevance.REPORT = original
            self.assertFalse(stats["passed"])
            self.assertIn("BELUM LULUS", path.read_text(encoding="utf-8"))

    def test_full_labelled_sheet_passes_above_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = self._sheet(tmp, ["y"] * 90 + ["n"] * 10)
            out = Path(tmp) / "report.md"
            original = relevance.REPORT
            relevance.REPORT = out
            try:
                path, stats = relevance.score_review(sheet)
            finally:
                relevance.REPORT = original
            self.assertTrue(stats["passed"])
            self.assertIn("LULUS", path.read_text(encoding="utf-8"))

    def test_full_labelled_sheet_fails_below_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = self._sheet(tmp, ["y"] * 80 + ["n"] * 20)
            out = Path(tmp) / "report.md"
            original = relevance.REPORT
            relevance.REPORT = out
            try:
                path, stats = relevance.score_review(sheet)
            finally:
                relevance.REPORT = original
            self.assertFalse(stats["passed"])
            self.assertIn("BELUM LULUS", path.read_text(encoding="utf-8"))

    def _run_sampler(self, tmp, rows, n=100):
        """Call the real sampler against a temporary sheet, twice."""
        sheet = Path(tmp) / "review.csv"
        original_texts, original_csv = relevance._texts, relevance.REVIEW_CSV
        relevance._texts = lambda tag=None: rows
        relevance.REVIEW_CSV = sheet
        try:
            relevance.sample_for_review(n=n)
            first = list(csv.DictReader(sheet.open(encoding="utf-8")))
            sheet.unlink()  # clear it so the second draw is not blocked
            relevance.sample_for_review(n=n)
            second = list(csv.DictReader(sheet.open(encoding="utf-8")))
        finally:
            relevance._texts, relevance.REVIEW_CSV = original_texts, original_csv
        return first, second

    def test_sample_for_review_draws_seeded_random_rows(self):
        rows = [{"text_id": f"t{i}", "player_id": f"p{i % 7}", "unit_type": "comment"}
                for i in range(400)]
        with tempfile.TemporaryDirectory() as tmp:
            first, second = self._run_sampler(tmp, rows)
        seed = int(relevance.load_config()["text_sample"]["random_seed"])
        expected = [r["text_id"] for r in random.Random(seed).sample(rows, 100)]
        self.assertEqual([r["text_id"] for r in first], expected)
        # Same seed, second run: identical sheet, and no label pre-filled.
        self.assertEqual([r["text_id"] for r in second], expected)
        self.assertTrue(all(r["relevant"] == "" for r in first))

    def test_sample_for_review_refuses_to_clear_a_labelled_sheet(self):
        rows = [{"text_id": f"t{i}", "player_id": "p1", "unit_type": "comment"} for i in range(120)]
        with tempfile.TemporaryDirectory() as tmp:
            first, _ = self._run_sampler(tmp, rows)
            self.assertEqual(len(first), 100)
            # Team fills in one label; a redraw must not silently erase it.
            sheet = Path(tmp) / "review.csv"
            filled = list(csv.DictReader(sheet.open(encoding="utf-8")))
            filled[0]["relevant"] = "y"
            with sheet.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=relevance.FIELDS)
                writer.writeheader()
                writer.writerows(filled)
            original_texts, original_csv = relevance._texts, relevance.REVIEW_CSV
            relevance._texts = lambda tag=None: rows
            relevance.REVIEW_CSV = sheet
            try:
                with self.assertRaises(SystemExit):
                    relevance.sample_for_review(n=100)
            finally:
                relevance._texts, relevance.REVIEW_CSV = original_texts, original_csv
            self.assertEqual(
                sum(1 for r in csv.DictReader(sheet.open(encoding="utf-8"))
                    if r["relevant"] == "y"),
                1,
            )

    def test_partly_blank_sheet_never_passes(self):
        # 100 labels would be enough, but blank rows mean texts nobody read.
        with tempfile.TemporaryDirectory() as tmp:
            sheet = self._sheet(tmp, ["y"] * 100 + [""] * 100)
            out = Path(tmp) / "report.md"
            original = relevance.REPORT
            relevance.REPORT = out
            try:
                path, stats = relevance.score_review(sheet)
            finally:
                relevance.REPORT = original
            self.assertFalse(stats["passed"])
            self.assertIn("BELUM LULUS", path.read_text(encoding="utf-8"))

if __name__ == "__main__":
    unittest.main()
