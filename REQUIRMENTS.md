requirements:

I have a directory structure with markdown, html, video , images, text and pdf's and i would like to use them inside obsyndian
obsidian only handles markdowns for search so i would like to go through all documents and if we find images or pdf's i would like to run an ocr model (using LM Studio with qwen/qwen3-vl-8b)
the output should be in .md format in a way that obsidian still sees it.
maybe if we find a file like: a/b/c/d/f.pdf create a a/b/c/d/.f.pdf directory and put f.md in there with the ocr text ?
is that doable, and visible ?
if that file is already there, don't bother with the ocr, just skip it
print out an overview once it has run
use python 
create a venv and requirements.txt file
add a test to the project
create a project file
never put any private keys in the files, pick them up from the environment so i can add the project to a public github
