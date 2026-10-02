def test_pacote_ingestion_importavel():
    import ingestion
    import ingestion.common  # noqa: F401

    assert ingestion is not None
