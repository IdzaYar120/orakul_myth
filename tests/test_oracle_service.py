from delphi.rag.oracle import OracleService


def test_oracle_refusal_when_no_passages():
    oracle = OracleService()
    answer = oracle.ask("Який номер телефону в Зевса?")
    assert answer is not None
    assert answer.grounded is False
    assert "Дим над священним триножником розвіявся" in answer.text
