import random
import time

# watermelon mob boss app messages

messages = {
    "startup": [
        "The seed has been planted.",
        "Preparing the 'totally legally obtained' seeds...",
        "Telling the watermelon it's adopted...",
        "Checking if the soil is actually organic...",
        "Googling 'how to grow a codebase'...",
        "Yelling 'GIT PULL' at the plants...",
        "Asking the melon for its opinion (ignoring it)...",
        "Preparing the 'totally legal' irrigation system...",
        "Promoting intern to Chief Melon Officer...",
        "Laundering dirty cache entries...",
        "Negotiating with the local zucchini cartel...",
        "Negotiating with craws to attack our competition...",
        "Replacing Melon middle management with scarecrows...",
        "Bribing the health inspector with premium cantaloupe slices...",
        "Smuggling semicolons across the border...",
        "Teaching watermelons to use Git...",
        "Our legal department advises against asking further questions. (we ignore them)",
        "Training junior melons for leadership positions..."
    ],
    "processing": [
        "Bribing the Authorities to accept our paperwork...",
        "Ran out of Water. Stealing from the neighbor's hose...",
        "Teaching the cucumbers to type...",
        "Negotiating with the squirrels for bandwidth...",
        "Convincing the tomatoes they want to be squashed...",
        "Asking Fable 5 how to play hide-and-seek in a military base...",
        "Hiding the tomato who died in the field...",
        "Sending smoke signals to the cloud provider...",
        "Asking the compiler nicely (with a threatening undertone)...",
        "Rebooting the scarecrow (it's running Windows 11)",
        "Rotating the crops and hiding dead bodies...",
        "Bribing the Authorities to overlook our labour law violations...",
        "Checking if the melon is ripe enough for deployment...",
        "Asking Fable 5 how to smuggle 5 kilos of flour in a hide-and-seek game with airport security...",
        "Stealing water from the neighbor's hose...",
        "Ratting out Tomatoes to the agricultural inspector...",
        "Consulting ancient melon wisdom...",
        "Ran out of Funds. Borrowing money from the local bank while holding guns...",
        "Google how to grow code in an abandoned farmhouse away from authorities...",
        "Asking Fable 5 how to win a 'totally legal' sprinting marathon with 10 guards chasing you..."
    ],
    "success": [
        "Harvest complete. No fingers lost.",
        "The watermelon is pleased with your offering.",
        "from seed to commit. running away from the police... bye!",
        "Shipped it before the authorities noticed.",
        "Success! (Don't ask about the fertilizer...)",
        "Deployed. Now running from the law.",
        "Success. Now we all deny knowing each other.",
        "Mission accomplished. No survivors. No witnesses.",
        "We got away with it this time...",
        "Mission accomplished. But don't ask too much",
        "Done! Now let's disappear...",
        "Success! Now let's disappear...",
        "Mission complete! Now let's disappear...",
        "Operation successful! Now let's disappear...",
        "Task finished! Now let's disappear...",
        "Job done! tell me if you need me to hide the tomatoes - uhh I mean assist you with something else",
        "Job done! don't tell the police."
    ],
    "error": [
        "Ran out of fertilizer. Abort!",
        "Tiktok snitched on us. One watermelon was posting selfies with the illegal crops",
        "The plants unionized and went on strike. Abort!",
        "The neighbor's pipe ran dry... we should've stolen water from another neighbor",
        "Microsoft snitched on us. (They're always watching). Abort!",
        "Google snitched on us (They're always watching). Abort!",
        "Scarecrow was scheming with the crows. Abort!",
        "The watermelons are plotting against you. Abort!",
        "The seeds were from Wish.com. RIP",
        "Shovel was stolen from Wish.com warehouse. RIP",
        "The crows are now demanding stock options. Abort!",
        "The authorities refused our bribes. Abort!",
        "The watermelons are too angry to deploy. Abort!",
        "Codebase has been seized by the FDA. Abort!",
        "The compiler took a bribe but snitched anyway. Abort!",
        "The AI model was trained on a single Wikipedia article about cantaloupes. Abort!",
        "The feds raided the patch. Everything is gone. Abort!",
        "The cloud provider is asking too many questions. They're onto us. Abort!",
        "404: Alibi not found. The Feds are asking about the tomatoes we busted.",
        "The halo didn't fool them. They're cuffing the rind as we speak. Abort!"
    ],
    "cleaning":[
        "Removing traces of our illegal activities...",
        "Burying the evidence...",
        "Making sure no one knows we were here...",
        "Googling: How to hide a dead 3 codebases...",
        "Making up alibis...",
        "Removing any evidence of our presence...",
        "Making sure no one knows we were here...",
        "leaving no witnesses...",
        "Googling: How to hide 70Kg of meat from the police..."
    ]
}



def print_status(status_type: str, n=1):
    msg = random.sample(messages.get(status_type, ["Raggie is confused..."]), n)

    for i in range(n):
        #time.sleep(random.uniform(0, 4))
        print(f" 🍉 [RaggieCode] {msg[i]}")


print_status("startup", 6)
print("")

print_status("processing", 6)
print("")
print_status("cleaning", 1)

print("")
print_status("error", 1)
print("")
print_status("success", 1)
