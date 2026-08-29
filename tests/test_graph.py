from app.agents.tools import shopper_is_reached


def test_jules_reached_only_when_student_is_targeted():
    broad = {"roles": ["plant_manager", "student"]}
    tight = {"roles": ["plant_manager", "operations_manager"]}
    assert shopper_is_reached("jules", broad) is True
    assert shopper_is_reached("jules", tight) is False
    assert shopper_is_reached("klaus", tight) is True
