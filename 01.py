from paddleocr import PPStructureV3

pipeline = PPStructureV3(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False
)

output = pipeline.predict(
    input="./test1.jpg"
)

for res in output:
    res.print()
    res.save_to_json(save_path="./")
    res.save_to_markdown(save_path="./")