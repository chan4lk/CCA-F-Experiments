from plan import MAP, RANK, WORK, Investigation


def test_a_dependency_holds_a_task_back():
    inv = Investigation(goal="add tests")
    inv.add("map the package", "structure first", weight=5)
    inv.add("test the refund path", "highest churn", weight=4, blocked_by=["map the package"])

    assert [t.question for t in inv.ready] == ["map the package"]
    assert len(inv.blocked) == 1


def test_completing_a_task_unblocks_what_depended_on_it():
    inv = Investigation(goal="add tests")
    inv.add("map the package", "structure first", weight=5)
    inv.add("test the refund path", "highest churn", weight=4, blocked_by=["map the package"])

    inv.complete("map the package")

    assert [t.question for t in inv.ready] == ["test the refund path"]
    assert inv.blocked == []


def test_ready_work_is_ordered_by_weight():
    inv = Investigation(goal="g")
    inv.add("low", "", weight=1)
    inv.add("high", "", weight=9)

    assert [t.question for t in inv.ready] == ["high", "low"]


def test_a_task_added_mid_investigation_competes_immediately():
    inv = Investigation(goal="g")
    inv.add("first", "", weight=2)
    inv.add("discovered later", "found while reading", weight=8)

    assert inv.ready[0].question == "discovered later"


def test_open_questions_feed_the_manifest():
    inv = Investigation(goal="g")
    inv.add("a", "")
    inv.add("b", "")
    inv.complete("a")

    assert inv.open_questions == ["b"]


def test_phases_advance_map_rank_work():
    inv = Investigation(goal="g")
    assert inv.phase == MAP
    assert inv.advance() == RANK
    assert inv.advance() == WORK
    assert inv.advance() == WORK
